from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import pytest
from qdrant_client import models

from ai_pcb.evidence.chunking import EngineeringChunker
from ai_pcb.evidence.embedding import FastEmbedProvider
from ai_pcb.evidence.errors import EmbeddingError, MissingIndexError
from ai_pcb.evidence.evaluation import evaluate_retrieval, evaluate_retrieval_corpora
from ai_pcb.evidence.query import classify_engineering_query
from ai_pcb.evidence.retrieval import QdrantHybridEvidenceIndex
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import (
    BlockKind,
    BoundingBox,
    ChunkKind,
    DocumentBlock,
    DocumentChunk,
    DocumentMetadata,
    DocumentPage,
    DocumentRecord,
    DocumentSection,
    EngineeringEvidenceQuery,
    ExtractionStatus,
    QueryIntent,
    RetrievalEvaluationCase,
    RetrievalMethod,
)


def test_fastembed_uses_bounded_batches_for_large_real_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingModel:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            self.batch_sizes.append(len(texts))
            return [[1.0, 0.0] for _ in texts]

    model = RecordingModel()
    provider = FastEmbedProvider(batch_size=3)
    monkeypatch.setattr(provider, "_load", lambda: model)
    vectors = provider.embed_documents([f"chunk {index}" for index in range(8)])
    assert len(vectors) == 8
    assert model.batch_sizes == [3, 3, 2]


class SyntheticSemanticEmbedding:
    model_name = "synthetic-semantic-v1"
    dimension = 8

    _concepts: ClassVar[dict[str, int]] = {
        "dvdd": 0,
        "digital": 0,
        "processing": 0,
        "dsp": 0,
        "core": 0,
        "supply": 1,
        "voltage": 1,
        "powers": 1,
        "requires": 1,
        "power": 1,
        "clock": 2,
        "mclk": 2,
        "master": 2,
        "adau1467": 3,
        "snr": 4,
        "noise": 4,
    }

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for raw in text.lower().replace("?", "").replace(".", "").split():
            index = self._concepts.get(raw.strip("(),"))
            if index is not None:
                vector[index] += 1.0
        if not any(vector):
            vector[7] = 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def record(part: str, paragraphs: list[tuple[str, str]], *, suffix: str) -> DocumentRecord:
    digest = hashlib.sha256(f"{part}-{suffix}".encode()).hexdigest()
    document_id = f"doc-{digest[:24]}"
    blocks: list[DocumentBlock] = []
    sections: list[DocumentSection] = []
    order = 0
    for index, (section, text) in enumerate(paragraphs):
        heading_id = f"heading-{suffix}-{index}"
        section_id = f"section-{suffix}-{index}"
        blocks.append(
            DocumentBlock(
                block_id=heading_id,
                page=1,
                reading_order=order,
                kind=BlockKind.HEADING,
                text=section,
                section=section,
                bbox=BoundingBox(x0=10.0, y0=float(order * 10), x1=200.0, y1=float(order * 10 + 8)),
            )
        )
        order += 1
        blocks.append(
            DocumentBlock(
                block_id=f"paragraph-{suffix}-{index}",
                page=1,
                reading_order=order,
                kind=BlockKind.PARAGRAPH,
                text=text,
                section=section,
                bbox=BoundingBox(x0=10.0, y0=float(order * 10), x1=500.0, y1=float(order * 10 + 8)),
            )
        )
        order += 1
        sections.append(
            DocumentSection(
                section_id=section_id,
                title=section,
                page=1,
                heading_block_id=heading_id,
            )
        )
    metadata = DocumentMetadata(
        document_id=document_id,
        source_file=f"missing/{part}-{suffix}.pdf",
        sha256=digest,
        source_type=EvidenceSource.DATASHEET,
        manufacturer="Analog Devices",
        part_number=part,
        title=f"{part} Synthetic Datasheet",
        revision="A",
        total_pages=1,
    )
    page = DocumentPage(
        page_number=1,
        width=600.0,
        height=800.0,
        extraction_status=ExtractionStatus.COMPLETE,
        machine_readable_characters=sum(len(block.text) for block in blocks),
        blocks=blocks,
        section_ids=[section.section_id for section in sections],
    )
    chunks = EngineeringChunker(target_characters=300, max_characters=600).chunk(metadata, [page])
    return DocumentRecord(metadata=metadata, pages=[page], sections=sections, chunks=chunks)


def build_index(tmp_path: Path) -> tuple[QdrantHybridEvidenceIndex, DocumentRecord, DocumentRecord]:
    dsp = record(
        "ADAU1467",
        [
            ("POWER REQUIREMENTS", "The DVDD digital processing core supply requires 1.2 V."),
            ("CLOCK REQUIREMENTS", "Register PLL_CTRL configures MCLK. BCLK appears on pin 12."),
            ("PERFORMANCE", "The signal to noise ratio is listed as SNR 104 dB."),
        ],
        suffix="dsp",
    )
    codec = record(
        "ADAU1977",
        [("POWER REQUIREMENTS", "The converter AVDD supply requires 3.3 V.")],
        suffix="codec",
    )
    index = QdrantHybridEvidenceIndex(
        path=tmp_path / "qdrant",
        ingestion_path=tmp_path / "ingestion",
        embedding_provider=SyntheticSemanticEmbedding(),
    )
    index.index_document(dsp)
    index.index_document(codec)
    return index, dsp, codec


def test_exact_lexical_dense_semantic_and_hybrid_retrieval(tmp_path: Path) -> None:
    index, dsp, _ = build_index(tmp_path)
    try:
        exact = index.search(
            EngineeringEvidenceQuery(query="ADAU1467 PLL_CTRL MCLK pin 12", top_k=3)
        )
        assert exact[0].document_id == dsp.metadata.document_id
        assert exact[0].scores.lexical is not None
        semantic = index.search(
            EngineeringEvidenceQuery(
                query="What voltage powers the digital processing core?", top_k=2
            )
        )
        assert semantic[0].document_id == dsp.metadata.document_id
        assert semantic[0].scores.dense is not None
        assert semantic[0].retrieval_method is RetrievalMethod.HYBRID
    finally:
        index.close()


def test_metadata_filter_prevents_cross_part_leakage(tmp_path: Path) -> None:
    index, dsp, codec = build_index(tmp_path)
    try:
        results = index.search(
            EngineeringEvidenceQuery(
                query="supply voltage",
                part_number="ADAU1977",
                top_k=5,
            )
        )
        assert results
        assert {result.document_id for result in results} == {codec.metadata.document_id}
        assert dsp.metadata.document_id not in {result.document_id for result in results}
    finally:
        index.close()


def test_context_expansion_is_neighbor_bounded_and_provenanced(tmp_path: Path) -> None:
    index, _, _ = build_index(tmp_path)
    try:
        result = index.search(
            EngineeringEvidenceQuery(query="PLL_CTRL MCLK", top_k=1, context_expansion=1)
        )[0]
        assert 1 <= len(result.context) <= 2
        assert all(piece.chunk_id != result.chunk_id for piece in result.context)
        assert all(piece.locator.startswith("page=") for piece in result.context)
        assert result.locator.startswith("page=1;bbox(")
    finally:
        index.close()


def test_unchanged_reindex_is_idempotent_and_changed_source_replaces(tmp_path: Path) -> None:
    index, dsp, _ = build_index(tmp_path)
    try:
        before = index.client.count(index.collection_name, exact=True).count
        report = index.index_document(dsp)
        after = index.client.count(index.collection_name, exact=True).count
        assert report.unchanged
        assert report.chunks_created == 0
        assert after == before

        changed = record(
            "ADAU1467",
            [("POWER REQUIREMENTS", "DVDD core supply requires 1.1 V.")],
            suffix="changed",
        )
        changed_metadata = changed.metadata.model_copy(
            update={"source_file": dsp.metadata.source_file}
        )
        changed = changed.model_copy(
            update={
                "metadata": changed_metadata,
                "chunks": [
                    chunk.model_copy(update={"source_file": dsp.metadata.source_file})
                    for chunk in changed.chunks
                ],
            }
        )
        changed_report = index.index_document(changed)
        assert changed_report.previous_document_hash == dsp.metadata.sha256
        old_points, _ = index.client.scroll(
            index.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=dsp.metadata.document_id),
                    )
                ]
            ),
        )
        assert old_points == []
    finally:
        index.close()


def test_retrieval_evaluation_reports_recall_and_mrr(tmp_path: Path) -> None:
    index, dsp, _ = build_index(tmp_path)
    try:
        fixture_path = Path("knowledge/evaluation/synthetic_queries.json")
        cases = [
            RetrievalEvaluationCase.model_validate(case)
            for case in json.loads(fixture_path.read_text(encoding="utf-8"))
        ]
        assert {case.expected_document_id for case in cases} == {dsp.metadata.document_id}
        metrics = evaluate_retrieval(index, cases)
        assert metrics.cases == 2
        assert metrics.recall_at_k == 1.0
        assert metrics.mean_reciprocal_rank == 1.0
    finally:
        index.close()


def test_synthetic_and_real_datasheet_metrics_are_reported_separately(
    tmp_path: Path,
) -> None:
    index, _, _ = build_index(tmp_path)
    try:
        synthetic_path = Path("knowledge/evaluation/synthetic_queries.json")
        real_path = Path("knowledge/evaluation/real_datasheet_queries.json")
        synthetic = [
            RetrievalEvaluationCase.model_validate(case)
            for case in json.loads(synthetic_path.read_text(encoding="utf-8"))
        ]
        real = [
            RetrievalEvaluationCase.model_validate(case)
            for case in json.loads(real_path.read_text(encoding="utf-8"))
        ]
        metrics = evaluate_retrieval_corpora(
            index, synthetic_cases=synthetic, real_datasheet_cases=real
        )
        assert metrics.synthetic.cases == 2
        assert metrics.synthetic.recall_at_k == 1.0
        assert metrics.synthetic.mean_reciprocal_rank == 1.0
        assert metrics.real_datasheets.cases == 31
        assert metrics.real_datasheets.recall_at_k == 0.0
        assert metrics.real_datasheets.mean_reciprocal_rank == 0.0
        assert metrics.real_corpus_meaningful
    finally:
        index.close()


def test_phase33_holdout_queries_are_valid_and_distinct_from_tuned_cases() -> None:
    tuned_raw = json.loads(
        Path("knowledge/evaluation/real_datasheet_queries.json").read_text(encoding="utf-8")
    )
    holdout_raw = json.loads(
        Path("knowledge/evaluation/phase33_holdout_queries.json").read_text(encoding="utf-8")
    )
    holdout = [RetrievalEvaluationCase.model_validate(case) for case in holdout_raw]
    assert len(holdout) == 10
    assert {case.case_id for case in holdout}.isdisjoint(
        {str(case["case_id"]) for case in tuned_raw}
    )
    assert len({case.query.query for case in holdout}) == len(holdout)


def test_missing_index_and_embedding_failure_are_explicit(tmp_path: Path) -> None:
    missing = QdrantHybridEvidenceIndex(
        path=tmp_path / "missing-qdrant",
        ingestion_path=tmp_path / "missing-ingestion",
        embedding_provider=SyntheticSemanticEmbedding(),
    )
    try:
        with pytest.raises(MissingIndexError):
            missing.search(EngineeringEvidenceQuery(query="DVDD"))
    finally:
        missing.close()

    class FailingEmbedding(SyntheticSemanticEmbedding):
        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            raise EmbeddingError("synthetic embedding failure")

    failing = QdrantHybridEvidenceIndex(
        path=tmp_path / "failing-qdrant",
        ingestion_path=tmp_path / "failing-ingestion",
        embedding_provider=FailingEmbedding(),
    )
    try:
        with pytest.raises(EmbeddingError, match="synthetic"):
            failing.index_document(
                record(
                    "ADAU1467",
                    [("POWER", "DVDD supply requires 1.2 V.")],
                    suffix="failure",
                )
            )
    finally:
        failing.close()


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("PLL_CTRL register value", QueryIntent.EXACT_IDENTIFIER),
        ("analog supply voltage operating range", QueryIntent.ELECTRICAL_SPECIFICATION),
        ("I2S TDM master clock", QueryIntent.INTERFACE_CLOCK),
        ("ADC SNR and THD+N", QueryIntent.PERFORMANCE),
        ("digital filter group delay", QueryIntent.TIMING_LATENCY),
        ("PowerPAD thermal layout", QueryIntent.LAYOUT_THERMAL),
        ("recommended application", QueryIntent.GENERAL_SEMANTIC),
    ],
)
def test_query_intent_classification_is_deterministic(query: str, intent: QueryIntent) -> None:
    first = classify_engineering_query(query)
    assert first == classify_engineering_query(query)
    assert first.intent is intent


def test_query_decomposition_and_ranking_controls_are_typed() -> None:
    classification = classify_engineering_query(
        "ADC SNR and THD+N differential, output noise conditions"
    )
    assert classification.intent is QueryIntent.PERFORMANCE
    assert len(classification.decomposed_queries) >= 3
    assert classification.prefer_overview
    assert classify_engineering_query("precision clock generator count").prefer_overview


def test_table_symbol_normalization_overview_boost_and_page_diversity(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"rank-hardening").hexdigest()
    document_id = f"doc-{digest[:24]}"
    metadata = DocumentMetadata(
        document_id=document_id,
        source_file="missing/rank-hardening.pdf",
        sha256=digest,
        source_type=EvidenceSource.DATASHEET,
        manufacturer="Test Manufacturer",
        part_number="RANK-1",
        title="Ranking hardening fixture",
        total_pages=3,
    )
    raw = [
        (
            1,
            "GENERAL DESCRIPTION",
            ChunkKind.TEXT,
            "Eight DAC output channels support 192 kHz audio.",
        ),
        (2, "REGISTER MAP", ChunkKind.TEXT, "DAC output channel register " * 30),
        (
            3,
            "RECOMMENDED OPERATING CONDITIONS",
            ChunkKind.TABLE,
            "PARAMETER | MIN | MAX | UNIT\nPVDD | 4.5 | 26.4 | V\nLOAD | 4 | 4 | Ω",
        ),
    ]
    chunks = [
        DocumentChunk(
            chunk_id=f"chunk-rank-{page}",
            document_id=document_id,
            source_file=metadata.source_file,
            document_hash=digest,
            source_type=EvidenceSource.DATASHEET,
            manufacturer=metadata.manufacturer,
            part_number=metadata.part_number,
            document_title=metadata.title,
            page=page,
            section=section,
            kind=kind,
            text=text,
            locator=f"page={page}",
            previous_chunk_id=f"chunk-rank-{page - 1}" if page > 1 else None,
            next_chunk_id=f"chunk-rank-{page + 1}" if page < 3 else None,
        )
        for page, section, kind, text in raw
    ]
    pages = [
        DocumentPage(
            page_number=page,
            width=600,
            height=800,
            extraction_status=ExtractionStatus.COMPLETE,
            machine_readable_characters=len(text),
        )
        for page, _, _, text in raw
    ]
    record = DocumentRecord(metadata=metadata, pages=pages, sections=[], chunks=chunks)
    index = QdrantHybridEvidenceIndex(
        path=tmp_path / "rank-qdrant",
        ingestion_path=tmp_path / "rank-ingestion",
        embedding_provider=SyntheticSemanticEmbedding(),
    )
    try:
        index.index_document(record)
        overview = index.search(
            EngineeringEvidenceQuery(
                query="number of DAC output channels and supported sampling rate",
                part_number="RANK-1",
                top_k=3,
            )
        )
        assert overview[0].page == 1
        assert len({item.page for item in overview}) == len(overview)
        table = index.search(
            EngineeringEvidenceQuery(
                query="PVDD operating range and 4 ohm load",
                part_number="RANK-1",
                top_k=3,
                context_expansion=1,
            )
        )
        assert table[0].page == 3
        assert any(piece.page == 2 for piece in table[0].context)
    finally:
        index.close()
