from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pymupdf
import pytest

from ai_pcb.evidence.acquisition import (
    HttpManufacturerDocumentationProvider,
    ManufacturerEvidenceAcquisitionPipeline,
    load_acquisition_manifest,
)
from ai_pcb.evidence.errors import InvalidDownloadedDocumentError, UntrustedSourceError
from ai_pcb.evidence.ingestion import PdfDocumentIngestor
from ai_pcb.evidence.retrieval import QdrantHybridEvidenceIndex
from ai_pcb.models.acquisition import (
    AcquisitionCatalog,
    AcquisitionManifest,
    AcquisitionRequest,
    AcquisitionUrlOrigin,
    AcquisitionVerificationStatus,
    ManufacturerDocumentType,
)
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import DocumentRecord, EngineeringEvidenceQuery, IngestionReport


def _pdf(*, part_number: str = "ADSP-21569", revision: str = "Rev. D") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 60), f"{part_number} Data Sheet {revision}")
    page.insert_text((50, 90), "Copyright Analog Devices, Inc.")
    page.insert_text((50, 120), "Four SPORT audio interfaces and FIR accelerator.")
    content = document.tobytes()
    document.close()
    return content


def _request(
    url: str = "https://www.analog.com/data.pdf",
    *,
    part_number: str = "ADSP-21569",
    origin: AcquisitionUrlOrigin = AcquisitionUrlOrigin.CURATED_MANIFEST,
) -> AcquisitionRequest:
    return AcquisitionRequest(
        manufacturer="Analog Devices",
        part_number=part_number,
        document_type=ManufacturerDocumentType.DATASHEET,
        canonical_source_url=url,
        url_origin=origin,
    )


def _provider(
    tmp_path: Path, handler: httpx.MockTransport
) -> HttpManufacturerDocumentationProvider:
    return HttpManufacturerDocumentationProvider(
        knowledge_root=tmp_path / "knowledge",
        trusted_domains={
            "Analog Devices": ["analog.com"],
            "Texas Instruments": ["ti.com"],
        },
        client=httpx.Client(transport=handler, follow_redirects=False),
    )


def test_untrusted_domain_cannot_become_manufacturer_evidence(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_pdf()))
    with pytest.raises(UntrustedSourceError, match="outside the trusted"):
        _provider(tmp_path, transport).acquire(_request("https://example-files.invalid/fake.pdf"))


def test_trusted_redirect_to_untrusted_domain_is_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://mirror.invalid/adsp.pdf"},
            request=request,
        )

    with pytest.raises(UntrustedSourceError, match="outside the trusted"):
        _provider(tmp_path, httpx.MockTransport(handler)).acquire(_request())


def test_sha_is_recorded_and_duplicate_is_idempotent(tmp_path: Path) -> None:
    content = _pdf()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=content,
            request=request,
        )
    )
    provider = _provider(tmp_path, transport)
    first = provider.acquire(_request())
    second = provider.acquire(_request())
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert Path(first.local_path).read_bytes() == content
    assert second.local_path == first.local_path
    assert second.unchanged
    catalog = AcquisitionCatalog.model_validate_json(provider.catalog_path.read_text())
    assert len(catalog.documents) == 1
    assert len(catalog.events) == 1


def test_changed_document_preserves_previous_version(tmp_path: Path) -> None:
    contents = iter([_pdf(revision="Rev. C"), _pdf(revision="Rev. D")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=next(contents),
            request=request,
        )

    provider = _provider(tmp_path, httpx.MockTransport(handler))
    first = provider.acquire(_request())
    second = provider.acquire(_request())
    assert first.sha256 != second.sha256
    assert first.local_path != second.local_path
    assert Path(first.local_path).is_file()
    assert Path(second.local_path).is_file()
    assert second.previous_sha256 == first.sha256
    catalog = AcquisitionCatalog.model_validate_json(provider.catalog_path.read_text())
    assert catalog.events[-1].kind.value == "CONTENT_CHANGED"


def test_invalid_non_pdf_response_fails_closed(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html>not a datasheet</html>",
            request=request,
        )
    )
    with pytest.raises(InvalidDownloadedDocumentError, match="not an application/pdf"):
        _provider(tmp_path, transport).acquire(_request())


def test_wrong_part_number_document_is_not_trusted(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf(part_number="ADAU1978"),
            request=request,
        )
    )
    result = _provider(tmp_path, transport).acquire(_request())
    assert result.verification_status is AcquisitionVerificationStatus.IDENTITY_UNVERIFIED
    assert "quarantine" in Path(result.local_path).parts


def test_manifest_parsing_is_typed(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """documents:
  - manufacturer: Analog Devices
    part_number: ADSP-21569
    document_type: DATASHEET
    canonical_source_url: https://www.analog.com/data.pdf
""",
        encoding="utf-8",
    )
    manifest = load_acquisition_manifest(manifest_path)
    assert isinstance(manifest, AcquisitionManifest)
    assert manifest.documents[0].document_type is ManufacturerDocumentType.DATASHEET


class _RecordingIndexer:
    def __init__(self) -> None:
        self.records: list[DocumentRecord] = []

    def index_document(self, record: DocumentRecord) -> IngestionReport:
        self.records.append(record)
        return IngestionReport(
            document_id=record.metadata.document_id,
            source_file=record.metadata.source_file,
            document_hash=record.metadata.sha256,
            pages_processed=len(record.pages),
            chunks_created=len(record.chunks),
        )


def test_acquisition_integrates_with_phase2_ingestion(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf(),
            request=request,
        )
    )
    indexer = _RecordingIndexer()
    result = ManufacturerEvidenceAcquisitionPipeline(
        _provider(tmp_path, transport),
        ingestor=PdfDocumentIngestor(ocr_minimum_characters=0),
        indexer=indexer,
    ).acquire_manifest(AcquisitionManifest(documents=[_request()]))
    assert not result.failed
    assert result.ingestion_reports
    provenance = indexer.records[0].metadata.acquisition
    assert provenance is not None
    assert provenance.verification_status is AcquisitionVerificationStatus.TRUSTED
    assert all(chunk.acquisition == provenance for chunk in indexer.records[0].chunks)


class _TinyEmbedding:
    model_name = "tiny-acquisition-test"
    dimension = 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, float("sport" in text.casefold())] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, float("sport" in text.casefold())]


def test_retrieval_retains_acquisition_provenance(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=_pdf(),
            request=request,
        )
    )
    result = _provider(tmp_path, transport).acquire(_request())
    record = PdfDocumentIngestor(ocr_minimum_characters=0).ingest(
        Path(result.local_path),
        source_type=EvidenceSource.DATASHEET,
        manufacturer=result.manufacturer,
        part_number=result.part_number,
        acquisition_provenance=result.provenance(),
    )
    index = QdrantHybridEvidenceIndex(
        path=tmp_path / "index",
        ingestion_path=tmp_path / "ingestion",
        embedding_provider=_TinyEmbedding(),
    )
    try:
        index.index_document(record)
        found = index.search(EngineeringEvidenceQuery(query="SPORT", top_k=1))[0]
        assert found.acquisition == result.provenance()
        assert found.document_hash == result.sha256
    finally:
        index.close()


def test_model_generated_url_is_not_blindly_trusted(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_pdf()))
    with pytest.raises(UntrustedSourceError, match="explicit curation"):
        _provider(tmp_path, transport).acquire(
            _request(origin=AcquisitionUrlOrigin.MODEL_GENERATED)
        )


def test_catalog_is_valid_json_contract(tmp_path: Path) -> None:
    content = _pdf()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=content,
            request=request,
        )
    )
    provider = _provider(tmp_path, transport)
    provider.acquire(_request())
    raw = json.loads(provider.catalog_path.read_text(encoding="utf-8"))
    assert raw["documents"][0]["sha256"] == hashlib.sha256(content).hexdigest()
