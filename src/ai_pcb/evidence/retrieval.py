from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

from qdrant_client import QdrantClient, models

from ai_pcb.evidence.embedding import EmbeddingProvider
from ai_pcb.evidence.errors import InconsistentDocumentHashError, MissingIndexError
from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.evidence import Evidence, EvidenceProvenance
from ai_pcb.models.knowledge import (
    DocumentChunk,
    DocumentRecord,
    EngineeringEvidenceCandidate,
    EngineeringEvidenceQuery,
    EvidenceContextPiece,
    IngestionIssue,
    IngestionReport,
    RetrievalMethod,
    RetrievalScores,
)

_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:[+.-][A-Za-z0-9_+.-]+)*")


class EvidenceRetriever(Protocol):
    def search(self, query: EngineeringEvidenceQuery) -> list[EngineeringEvidenceCandidate]: ...


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ai-pcb:{chunk_id}"))


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(text)]


class QdrantHybridEvidenceIndex:
    """Persistent embedded-Qdrant dense index with local BM25-style lexical fusion."""

    def __init__(
        self,
        *,
        path: Path,
        ingestion_path: Path,
        embedding_provider: EmbeddingProvider,
        collection_name: str = "engineering_evidence",
        rrf_constant: int = 60,
    ) -> None:
        self.path = path
        self.ingestion_path = ingestion_path
        self.embedding_provider = embedding_provider
        self.collection_name = collection_name
        self.rrf_constant = rrf_constant
        self.path.mkdir(parents=True, exist_ok=True)
        self.ingestion_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(self.path))
        self.registry_path = self.ingestion_path / "registry.json"

    def close(self) -> None:
        self.client.close()

    def _registry(self) -> dict[str, dict[str, str]]:
        if not self.registry_path.is_file():
            return {}
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        required = {
            "sha256",
            "document_id",
            "record",
            "embedding_model",
            "metadata_fingerprint",
            "chunk_fingerprint",
        }
        if not isinstance(raw, dict) or any(
            not isinstance(source, str)
            or not isinstance(entry, dict)
            or not required.issubset(entry)
            or any(not isinstance(entry[field], str) for field in required)
            for source, entry in raw.items()
        ):
            raise InconsistentDocumentHashError("ingestion registry is invalid")
        return cast(dict[str, dict[str, str]], raw)

    def _write_registry(self, registry: dict[str, dict[str, str]]) -> None:
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.registry_path)

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            info = self.client.get_collection(self.collection_name)
            vectors = info.config.params.vectors
            if (
                not isinstance(vectors, models.VectorParams)
                or vectors.size != self.embedding_provider.dimension
            ):
                raise InconsistentDocumentHashError(
                    "existing index vector dimension does not match configured embedding model"
                )
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedding_provider.dimension,
                distance=models.Distance.COSINE,
            ),
        )

    def index_document(self, record: DocumentRecord) -> IngestionReport:
        metadata = record.metadata
        source = Path(metadata.source_file)
        if source.is_file():
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual != metadata.sha256:
                raise InconsistentDocumentHashError(
                    f"document hash no longer matches source file: {metadata.source_file}"
                )
        registry = self._registry()
        prior = registry.get(metadata.source_file)
        previous_hash = prior.get("sha256") if prior else None
        self._ensure_collection()
        fingerprint = hashlib.sha256(
            metadata.model_dump_json().encode("utf-8")
        ).hexdigest()
        chunk_fingerprint = hashlib.sha256(
            "\0".join(chunk.chunk_id for chunk in record.chunks).encode("utf-8")
        ).hexdigest()
        if prior is not None and prior.get("embedding_model") != self.embedding_provider.model_name:
            raise InconsistentDocumentHashError(
                "configured embedding model differs from the existing index; use a new collection "
                "or rebuild the index"
            )
        current_count = 0
        if prior is not None:
            current_count = self.client.count(
                collection_name=self.collection_name,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=prior["document_id"]),
                        )
                    ]
                ),
                exact=True,
            ).count
        if (
            previous_hash == metadata.sha256
            and prior is not None
            and prior.get("metadata_fingerprint") == fingerprint
            and prior.get("chunk_fingerprint") == chunk_fingerprint
            and current_count == len(record.chunks)
        ):
            return self._report(record, previous_hash=previous_hash, unchanged=True)
        vectors = self.embedding_provider.embed_documents([chunk.text for chunk in record.chunks])
        if prior is not None and prior["document_id"] == metadata.document_id:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=prior["document_id"]),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        if record.chunks:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=_point_id(chunk.chunk_id),
                        vector=vector,
                        payload=self._payload(chunk),
                    )
                    for chunk, vector in zip(record.chunks, vectors, strict=True)
                ],
                wait=True,
            )
        if prior is not None and prior["document_id"] != metadata.document_id:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=prior["document_id"]),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        record_path = self.ingestion_path / f"{metadata.document_id}.json"
        temporary_record = record_path.with_suffix(".tmp")
        temporary_record.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary_record.replace(record_path)
        registry[metadata.source_file] = {
            "sha256": metadata.sha256,
            "document_id": metadata.document_id,
            "record": str(record_path),
            "embedding_model": self.embedding_provider.model_name,
            "metadata_fingerprint": fingerprint,
            "chunk_fingerprint": chunk_fingerprint,
        }
        self._write_registry(registry)
        return self._report(record, previous_hash=previous_hash, unchanged=False)

    @staticmethod
    def _report(
        record: DocumentRecord, *, previous_hash: str | None, unchanged: bool
    ) -> IngestionReport:
        ocr_pages = [
            page.page_number
            for page in record.pages
            if page.extraction_status.value == "REQUIRES_OCR"
        ]
        return IngestionReport(
            document_id=record.metadata.document_id,
            source_file=record.metadata.source_file,
            document_hash=record.metadata.sha256,
            previous_document_hash=previous_hash,
            pages_processed=len(record.pages),
            chunks_created=0 if unchanged else len(record.chunks),
            requires_ocr_pages=ocr_pages,
            issues=[
                IngestionIssue(
                    page=number,
                    code="REQUIRES_OCR",
                    message="insufficient machine-readable text",
                )
                for number in ocr_pages
            ],
            unchanged=unchanged,
        )

    @staticmethod
    def _payload(chunk: DocumentChunk) -> dict[str, object]:
        return {
            "chunk": chunk.model_dump(mode="json"),
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "source_type": chunk.source_type.value,
            "manufacturer": chunk.manufacturer,
            "part_number": chunk.part_number,
            "page": chunk.page,
            "section": chunk.section,
        }

    def search(self, query: EngineeringEvidenceQuery) -> list[EngineeringEvidenceCandidate]:
        if not self.client.collection_exists(self.collection_name):
            raise MissingIndexError(f"knowledge index does not exist: {self.collection_name}")
        query_filter = self._filter(query)
        candidate_limit = max(query.top_k * 5, 25)
        vector = self.embedding_provider.embed_query(query.query)
        dense_points = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=query_filter,
            limit=candidate_limit,
            with_payload=True,
        ).points
        dense: list[tuple[DocumentChunk, float]] = []
        for point in dense_points:
            chunk = self._chunk_from_payload(point.payload)
            dense.append((chunk, float(point.score)))
        lexical_chunks = self._filtered_chunks(query_filter)
        lexical = self._lexical_rank(query.query, lexical_chunks)[:candidate_limit]
        fused = self._fuse(dense, lexical, query.section_preference)
        selected = [
            entry
            for entry in fused
            if entry[1].fused >= query.minimum_retrieval_confidence
        ]
        results = [
            self._candidate(chunk, scores, method)
            for chunk, scores, method in selected[: query.top_k]
        ]
        if query.context_expansion:
            results = [
                result.model_copy(
                    update={
                        "context": self._expand(
                            result.document_id,
                            result.chunk_id,
                            query.context_expansion,
                        )
                    }
                )
                for result in results
            ]
        return results

    @staticmethod
    def _filter(query: EngineeringEvidenceQuery) -> models.Filter | None:
        conditions: list[models.Condition] = []
        if query.source_types:
            conditions.append(
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchAny(any=[item.value for item in query.source_types]),
                )
            )
        for key, value in (
            ("manufacturer", query.manufacturer),
            ("part_number", query.part_number),
            ("document_id", query.document_id),
        ):
            if value is not None:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        if query.pages:
            conditions.append(
                models.FieldCondition(key="page", match=models.MatchAny(any=query.pages))
            )
        return models.Filter(must=conditions) if conditions else None

    def _filtered_chunks(self, query_filter: models.Filter | None) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        offset: int | str | None = None
        while True:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            chunks.extend(self._chunk_from_payload(point.payload) for point in points)
            if next_offset is None:
                break
            offset = cast(int | str, next_offset)
        return chunks

    @staticmethod
    def _chunk_from_payload(payload: dict[str, object] | None) -> DocumentChunk:
        if payload is None or "chunk" not in payload:
            raise InconsistentDocumentHashError("indexed point is missing validated chunk metadata")
        # Strict JSON validation permits JSON enum strings while still rejecting coercive input.
        return DocumentChunk.model_validate_json(json.dumps(payload["chunk"]))

    @staticmethod
    def _lexical_rank(
        query: str, chunks: Sequence[DocumentChunk]
    ) -> list[tuple[DocumentChunk, float]]:
        query_terms = _tokens(query)
        if not query_terms or not chunks:
            return []
        documents = [_tokens(chunk.text) for chunk in chunks]
        average_length = sum(len(document) for document in documents) / len(documents)
        document_frequency = Counter(
            term for document in documents for term in set(document)
        )
        ranked: list[tuple[DocumentChunk, float]] = []
        for chunk, terms in zip(chunks, documents, strict=True):
            frequencies = Counter(terms)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if frequency == 0:
                    continue
                inverse = math.log(
                    1
                    + (len(chunks) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                denominator = frequency + 1.2 * (
                    0.25 + 0.75 * len(terms) / max(average_length, 1.0)
                )
                score += inverse * frequency * 2.2 / denominator
            if score > 0:
                ranked.append((chunk, score))
        return sorted(ranked, key=lambda item: (-item[1], item[0].chunk_id))

    def _fuse(
        self,
        dense: Sequence[tuple[DocumentChunk, float]],
        lexical: Sequence[tuple[DocumentChunk, float]],
        section_preference: str | None,
    ) -> list[tuple[DocumentChunk, RetrievalScores, RetrievalMethod]]:
        by_id: dict[str, dict[str, object]] = {}
        for rank, (chunk, score) in enumerate(dense, start=1):
            by_id.setdefault(chunk.chunk_id, {"chunk": chunk})
            by_id[chunk.chunk_id].update(dense=score, dense_rank=rank)
        for rank, (chunk, score) in enumerate(lexical, start=1):
            by_id.setdefault(chunk.chunk_id, {"chunk": chunk})
            by_id[chunk.chunk_id].update(lexical=score, lexical_rank=rank)
        maximum = 2 / (self.rrf_constant + 1)
        output: list[tuple[DocumentChunk, RetrievalScores, RetrievalMethod]] = []
        for values in by_id.values():
            contribution = 0.0
            if "dense_rank" in values:
                contribution += 1 / (self.rrf_constant + cast(int, values["dense_rank"]))
            if "lexical_rank" in values:
                contribution += 1 / (self.rrf_constant + cast(int, values["lexical_rank"]))
            chunk = cast(DocumentChunk, values["chunk"])
            fused_score = contribution / maximum
            if (
                section_preference
                and chunk.section
                and section_preference.casefold() in chunk.section.casefold()
            ):
                fused_score = min(1.0, fused_score + 0.05)
            has_dense = "dense" in values
            has_lexical = "lexical" in values
            method = (
                RetrievalMethod.HYBRID
                if has_dense and has_lexical
                else RetrievalMethod.DENSE
                if has_dense
                else RetrievalMethod.LEXICAL
            )
            output.append(
                (
                    chunk,
                    RetrievalScores(
                        dense=cast(float | None, values.get("dense")),
                        lexical=cast(float | None, values.get("lexical")),
                        fused=fused_score,
                    ),
                    method,
                )
            )
        return sorted(output, key=lambda item: (-item[1].fused, item[0].chunk_id))

    @staticmethod
    def _candidate(
        chunk: DocumentChunk, scores: RetrievalScores, method: RetrievalMethod
    ) -> EngineeringEvidenceCandidate:
        return EngineeringEvidenceCandidate(
            evidence_candidate_id=f"candidate-{chunk.chunk_id.removeprefix('chunk-')}",
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            source_file=chunk.source_file,
            source_type=chunk.source_type,
            manufacturer=chunk.manufacturer,
            part_number=chunk.part_number,
            document_title=chunk.document_title,
            document_revision=chunk.document_revision,
            acquisition=chunk.acquisition,
            document_hash=chunk.document_hash,
            page=chunk.page,
            section=chunk.section,
            locator=chunk.locator,
            extracted_text=chunk.text,
            scores=scores,
            retrieval_method=method,
        )

    def _expand(
        self, document_id: str, chunk_id: str, distance: int
    ) -> list[EvidenceContextPiece]:
        chunks = self._filtered_chunks(
            models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )
                ]
            )
        )
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        center = by_id.get(chunk_id)
        if center is None:
            raise InconsistentDocumentHashError(f"indexed context is missing chunk: {chunk_id}")
        selected: list[DocumentChunk] = []
        previous = center
        following = center
        for _ in range(distance):
            if previous.previous_chunk_id and previous.previous_chunk_id in by_id:
                previous = by_id[previous.previous_chunk_id]
                selected.insert(0, previous)
            if following.next_chunk_id and following.next_chunk_id in by_id:
                following = by_id[following.next_chunk_id]
                selected.append(following)
        return [
            EvidenceContextPiece(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_file=chunk.source_file,
                document_hash=chunk.document_hash,
                source_type=chunk.source_type,
                page=chunk.page,
                section=chunk.section,
                locator=chunk.locator,
                text=chunk.text,
                acquisition=chunk.acquisition,
            )
            for chunk in selected
        ]


def promote_retrieval_candidate(
    candidate: EngineeringEvidenceCandidate,
    store: EvidenceStore,
    *,
    normalized_fact: str,
    title: str,
    reviewed: bool,
) -> Evidence:
    """Promote human/reviewer-approved source text, never an unsupported model statement."""
    if not isinstance(candidate, EngineeringEvidenceCandidate):
        raise TypeError("only a retrieved evidence candidate can be promoted")
    if not reviewed:
        raise ValueError("retrieval evidence must be explicitly reviewed before promotion")
    evidence = Evidence(
        evidence_id=f"evidence-{candidate.chunk_id.removeprefix('chunk-')}",
        title=title,
        provenance=EvidenceProvenance(
            source=candidate.source_type,
            manufacturer=candidate.manufacturer,
            document=candidate.document_title,
            revision=candidate.document_revision,
            page=str(candidate.page),
            section=candidate.section,
            locator=candidate.locator,
            source_url=(candidate.acquisition.final_url if candidate.acquisition else None),
            sha256=candidate.document_hash,
            acquisition_id=(
                candidate.acquisition.acquisition_id if candidate.acquisition else None
            ),
        ),
        extracted_content=candidate.extracted_text,
        normalized_fact=normalized_fact,
        confidence=None,
        artifact_path=candidate.source_file,
    )
    store.add(evidence)
    return evidence
