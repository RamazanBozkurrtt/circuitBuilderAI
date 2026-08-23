from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
import pymupdf
import yaml

from ai_pcb.evidence.errors import (
    AcquisitionError,
    InvalidDownloadedDocumentError,
    UntrustedSourceError,
)
from ai_pcb.evidence.ingestion import PdfDocumentIngestor
from ai_pcb.models.acquisition import (
    AcquisitionBatchResult,
    AcquisitionCatalog,
    AcquisitionChangeEvent,
    AcquisitionChangeKind,
    AcquisitionFailure,
    AcquisitionManifest,
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionUrlOrigin,
    AcquisitionVerificationStatus,
    ManufacturerDocumentType,
)
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import DocumentRecord, IngestionReport


class DocumentationAcquisitionProvider(Protocol):
    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult: ...


class DocumentIndexer(Protocol):
    def index_document(self, record: DocumentRecord) -> IngestionReport: ...


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_NAME = re.compile(r"[^a-z0-9]+")
_DOCUMENT_TYPE_MARKERS: dict[ManufacturerDocumentType, tuple[str, ...]] = {
    ManufacturerDocumentType.DATASHEET: ("data sheet", "datasheet"),
    ManufacturerDocumentType.HARDWARE_REFERENCE: ("hardware reference",),
    ManufacturerDocumentType.APPLICATION_NOTE: (
        "application note",
        "application report",
        "engineer-to-engineer note",
        "engineer to engineer note",
    ),
    ManufacturerDocumentType.REFERENCE_DESIGN: ("reference design",),
    ManufacturerDocumentType.EVALUATION_BOARD_GUIDE: (
        "evaluation board",
        "evaluation module",
        "user's guide",
        "user guide",
    ),
    ManufacturerDocumentType.ERRATA: ("errata", "anomaly list"),
}
_MANUFACTURER_MARKERS: dict[str, tuple[str, ...]] = {
    "analog devices": ("analog devices", "analog devices, inc."),
    "texas instruments": ("texas instruments",),
}


def load_acquisition_manifest(path: Path) -> AcquisitionManifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AcquisitionManifest.model_validate_json(json.dumps(raw))


def _slug(value: str) -> str:
    slug = _SAFE_NAME.sub("_", value.casefold()).strip("_")
    return slug or "document"


def _identity_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _document_directory(document_type: ManufacturerDocumentType) -> str:
    return {
        ManufacturerDocumentType.DATASHEET: "datasheets",
        ManufacturerDocumentType.HARDWARE_REFERENCE: "reference_designs",
        ManufacturerDocumentType.APPLICATION_NOTE: "app_notes",
        ManufacturerDocumentType.REFERENCE_DESIGN: "reference_designs",
        ManufacturerDocumentType.EVALUATION_BOARD_GUIDE: "reference_designs",
        ManufacturerDocumentType.ERRATA: "errata",
    }[document_type]


def evidence_source_for(document_type: ManufacturerDocumentType) -> EvidenceSource:
    return EvidenceSource(document_type.value)


class HttpManufacturerDocumentationProvider:
    """HTTPS-only acquisition with per-hop domain checks and content-aware storage."""

    def __init__(
        self,
        *,
        knowledge_root: Path,
        trusted_domains: dict[str, list[str]],
        timeout_seconds: float = 45.0,
        max_redirects: int = 5,
        client: httpx.Client | None = None,
    ) -> None:
        self.knowledge_root = knowledge_root.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self._trusted_domains = {
            manufacturer.casefold(): tuple(domain.casefold().rstrip(".") for domain in domains)
            for manufacturer, domains in trusted_domains.items()
        }
        self._client = client
        self.metadata_root = self.knowledge_root / "acquisition_metadata"
        self.catalog_path = self.metadata_root / "catalog.json"

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        if request.canonical_source_url is None:
            raise AcquisitionError("acquisition request has no canonical manufacturer URL")
        if request.url_origin is AcquisitionUrlOrigin.MODEL_GENERATED:
            raise UntrustedSourceError(
                "model-generated URLs require explicit curation before acquisition"
            )
        original_url = request.canonical_source_url
        self._require_trusted_url(request.manufacturer, original_url)
        response, final_url = self._download(request.manufacturer, original_url)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        if response.status_code < 200 or response.status_code >= 300:
            raise InvalidDownloadedDocumentError(
                f"manufacturer document returned HTTP {response.status_code}"
            )
        content = response.content
        if content_type != "application/pdf" or not content.startswith(b"%PDF-"):
            raise InvalidDownloadedDocumentError(
                "downloaded response is not an application/pdf PDF document"
            )
        if len(content) < 32:
            raise InvalidDownloadedDocumentError("downloaded PDF is empty")
        extracted_text = self._extract_identity_text(content)
        status, messages = self._verify_identity(request, extracted_text)
        digest = hashlib.sha256(content).hexdigest()
        local_path = self._store_original(request, content, digest, status)
        acquisition_id = self._acquisition_id(original_url, digest)
        result = AcquisitionResult(
            acquisition_id=acquisition_id,
            original_url=original_url,
            final_url=final_url,
            manufacturer=request.manufacturer,
            part_number=request.part_number,
            document_type=request.document_type,
            content_type=content_type,
            sha256=digest,
            local_path=str(local_path),
            http_status=response.status_code,
            verification_status=status,
            verification_messages=messages,
        )
        return self._register(result)

    def _download(self, manufacturer: str, original_url: str) -> tuple[httpx.Response, str]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds, follow_redirects=False)
        current = original_url
        try:
            for redirect_count in range(self.max_redirects + 1):
                self._require_trusted_url(manufacturer, current)
                response = client.get(
                    current,
                    headers={"User-Agent": "ai-pcb-manufacturer-evidence/0.1"},
                )
                if response.status_code not in _REDIRECT_STATUSES:
                    return response, str(response.url)
                location = response.headers.get("location")
                if not location:
                    raise InvalidDownloadedDocumentError(
                        "redirect response did not include a Location header"
                    )
                if redirect_count == self.max_redirects:
                    raise InvalidDownloadedDocumentError("manufacturer redirect limit exceeded")
                current = urljoin(str(response.url), location)
                self._require_trusted_url(manufacturer, current)
        except httpx.HTTPError as exc:
            raise AcquisitionError(f"manufacturer document request failed: {exc}") from exc
        finally:
            if owns_client:
                client.close()
        raise InvalidDownloadedDocumentError("manufacturer document redirect resolution failed")

    def _require_trusted_url(self, manufacturer: str, url: str) -> None:
        domains = self._trusted_domains.get(manufacturer.casefold())
        if not domains:
            raise UntrustedSourceError(f"manufacturer is not allowlisted: {manufacturer}")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not any(
            host == domain or host.endswith(f".{domain}") for domain in domains
        ):
            raise UntrustedSourceError(
                f"URL host is outside the trusted manufacturer boundary: {host or '<missing>'}"
            )

    @staticmethod
    def _extract_identity_text(content: bytes) -> str:
        try:
            document = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
        except Exception as exc:
            raise InvalidDownloadedDocumentError("downloaded PDF cannot be opened") from exc
        try:
            if document.page_count < 1:
                raise InvalidDownloadedDocumentError("downloaded PDF has no pages")
            page_indexes = list(range(min(document.page_count, 16)))
            if document.page_count > 16:
                page_indexes.extend(range(max(16, document.page_count - 3), document.page_count))
            text = "\n".join(
                document.load_page(index).get_text()  # type: ignore[no-untyped-call]
                for index in page_indexes
            )
            if not text.strip():
                raise InvalidDownloadedDocumentError(
                    "downloaded PDF has no machine-readable identity text"
                )
            return text
        finally:
            document.close()  # type: ignore[no-untyped-call]

    def _verify_identity(
        self, request: AcquisitionRequest, extracted_text: str
    ) -> tuple[AcquisitionVerificationStatus, list[str]]:
        folded = extracted_text.casefold()
        normalized = _identity_text(extracted_text)
        failures: list[str] = []
        markers = _MANUFACTURER_MARKERS.get(request.manufacturer.casefold(), ())
        if not markers or not any(marker in folded for marker in markers):
            failures.append("expected manufacturer identity does not appear in the PDF")
        if _identity_text(request.part_number) not in normalized:
            failures.append("expected part number does not appear in the PDF")
        type_markers = _DOCUMENT_TYPE_MARKERS[request.document_type]
        if not any(marker in folded for marker in type_markers):
            failures.append("document type identity is not plausible from extracted PDF text")
        if request.expected_title and _identity_text(request.expected_title) not in normalized:
            failures.append("expected title does not appear in the PDF")
        if (
            request.expected_revision
            and _identity_text(request.expected_revision) not in normalized
        ):
            failures.append("expected revision does not appear in the PDF")
        if failures:
            return AcquisitionVerificationStatus.IDENTITY_UNVERIFIED, failures
        return AcquisitionVerificationStatus.TRUSTED, [
            "trusted domain, PDF format, manufacturer, part number, and document type verified"
        ]

    def _store_original(
        self,
        request: AcquisitionRequest,
        content: bytes,
        digest: str,
        status: AcquisitionVerificationStatus,
    ) -> Path:
        manufacturer_slug = _slug(request.manufacturer)
        if status is AcquisitionVerificationStatus.TRUSTED:
            directory = (
                self.knowledge_root
                / _document_directory(request.document_type)
                / manufacturer_slug
            )
        else:
            directory = self.knowledge_root / "quarantine" / manufacturer_slug
        directory.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{_slug(request.part_number)}-{request.document_type.value.casefold()}-"
            f"{digest[:16]}.pdf"
        )
        path = (directory / filename).resolve()
        if path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise InvalidDownloadedDocumentError(
                    "content-addressed acquisition path contains different bytes"
                )
            return path
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        return path

    @staticmethod
    def _acquisition_id(url: str, digest: str) -> str:
        identity = hashlib.sha256(f"{url}\0{digest}".encode()).hexdigest()[:24]
        return f"acquisition-{identity}"

    def _catalog(self) -> AcquisitionCatalog:
        if not self.catalog_path.is_file():
            return AcquisitionCatalog()
        return AcquisitionCatalog.model_validate_json(
            self.catalog_path.read_text(encoding="utf-8")
        )

    def _register(self, result: AcquisitionResult) -> AcquisitionResult:
        catalog = self._catalog()
        prior = next(
            (
                item
                for item in reversed(catalog.documents)
                if item.original_url == result.original_url
                and item.manufacturer == result.manufacturer
                and item.part_number == result.part_number
                and item.document_type is result.document_type
            ),
            None,
        )
        if prior is not None and prior.sha256 == result.sha256:
            return prior.model_copy(update={"unchanged": True})
        changed = prior is not None
        registered = result.model_copy(
            update={"previous_sha256": prior.sha256 if prior is not None else None}
        )
        event = AcquisitionChangeEvent(
            event_id=f"event-{hashlib.sha256(f'{registered.acquisition_id}|{len(catalog.events)}'.encode()).hexdigest()[:24]}",
            kind=(
                AcquisitionChangeKind.CONTENT_CHANGED
                if changed
                else AcquisitionChangeKind.ACQUIRED
            ),
            acquisition_id=registered.acquisition_id,
            original_url=registered.original_url,
            previous_sha256=prior.sha256 if prior is not None else None,
            sha256=registered.sha256,
        )
        updated = catalog.model_copy(
            update={
                "documents": [*catalog.documents, registered],
                "events": [*catalog.events, event],
            }
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        document_metadata = self.metadata_root / f"{registered.acquisition_id}.json"
        if not document_metadata.exists():
            document_metadata.write_text(
                registered.model_dump_json(indent=2), encoding="utf-8", newline="\n"
            )
        temporary = self.catalog_path.with_suffix(".tmp")
        temporary.write_text(updated.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        temporary.replace(self.catalog_path)
        return registered


class ManufacturerEvidenceAcquisitionPipeline:
    def __init__(
        self,
        provider: DocumentationAcquisitionProvider,
        *,
        ingestor: PdfDocumentIngestor | None = None,
        indexer: DocumentIndexer | None = None,
    ) -> None:
        if (ingestor is None) != (indexer is None):
            raise ValueError("automatic ingestion requires both an ingestor and an indexer")
        self.provider = provider
        self.ingestor = ingestor
        self.indexer = indexer

    def acquire_manifest(self, manifest: AcquisitionManifest) -> AcquisitionBatchResult:
        acquired: list[AcquisitionResult] = []
        failures: list[AcquisitionFailure] = []
        reports: list[dict[str, object]] = []
        for request in manifest.documents:
            try:
                result = self.provider.acquire(request)
                acquired.append(result)
                if self.ingestor is not None and self.indexer is not None:
                    if result.verification_status is not AcquisitionVerificationStatus.TRUSTED:
                        raise InvalidDownloadedDocumentError(
                            "identity-unverified documents cannot enter the evidence index"
                        )
                    record = self.ingestor.ingest(
                        Path(result.local_path),
                        source_type=evidence_source_for(result.document_type),
                        manufacturer=result.manufacturer,
                        part_number=result.part_number,
                        acquisition_provenance=result.provenance(),
                    )
                    reports.append(
                        self.indexer.index_document(record).model_dump(mode="json")
                    )
            except (AcquisitionError, OSError, ValueError) as exc:
                failures.append(AcquisitionFailure(request=request, error=str(exc)))
        return AcquisitionBatchResult(
            acquired=acquired,
            failed=failures,
            ingestion_reports=reports,
        )
