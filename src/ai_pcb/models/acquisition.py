from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, utc_now


class ManufacturerDocumentType(StrEnum):
    DATASHEET = "DATASHEET"
    HARDWARE_REFERENCE = "HARDWARE_REFERENCE"
    APPLICATION_NOTE = "APPLICATION_NOTE"
    REFERENCE_DESIGN = "REFERENCE_DESIGN"
    EVALUATION_BOARD_GUIDE = "EVALUATION_BOARD_GUIDE"
    ERRATA = "ERRATA"
    BOUNDARY_SCAN_DESCRIPTION = "BOUNDARY_SCAN_DESCRIPTION"


class AcquisitionUrlOrigin(StrEnum):
    USER_SUPPLIED = "USER_SUPPLIED"
    MANUFACTURER_PRODUCT_PAGE = "MANUFACTURER_PRODUCT_PAGE"
    CURATED_MANIFEST = "CURATED_MANIFEST"
    MODEL_GENERATED = "MODEL_GENERATED"


class AcquisitionVerificationStatus(StrEnum):
    TRUSTED = "TRUSTED"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    REJECTED = "REJECTED"


class AcquisitionChangeKind(StrEnum):
    ACQUIRED = "ACQUIRED"
    CONTENT_CHANGED = "CONTENT_CHANGED"
    VERIFICATION_CHANGED = "VERIFICATION_CHANGED"


class AcquisitionRequest(StrictModel):
    manufacturer: NonEmptyString
    part_number: NonEmptyString
    document_type: ManufacturerDocumentType
    canonical_source_url: str | None = None
    expected_title: str | None = None
    expected_revision: str | None = None
    url_origin: AcquisitionUrlOrigin = AcquisitionUrlOrigin.CURATED_MANIFEST

    @field_validator("canonical_source_url")
    @classmethod
    def valid_https_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("canonical source URL must be an HTTPS URL without credentials")
        return value

    @field_validator("expected_title", "expected_revision")
    @classmethod
    def nonblank_optional(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("expected document identity values cannot be blank")
        return value.strip() if value is not None else None


class AcquisitionManifest(StrictModel):
    documents: list[AcquisitionRequest] = Field(min_length=1)


class ManufacturerAcquisitionProvenance(StrictModel):
    acquisition_id: Identifier
    original_url: NonEmptyString
    final_url: NonEmptyString
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_status: AcquisitionVerificationStatus


class AcquisitionResult(StrictModel):
    acquisition_id: Identifier
    original_url: NonEmptyString
    final_url: NonEmptyString
    manufacturer: NonEmptyString
    part_number: NonEmptyString
    document_type: ManufacturerDocumentType
    content_type: NonEmptyString
    retrieved_at: datetime = Field(default_factory=utc_now)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_path: NonEmptyString
    http_status: int = Field(ge=100, le=599)
    verification_status: AcquisitionVerificationStatus
    verification_messages: list[NonEmptyString] = Field(default_factory=list)
    unchanged: bool = False
    previous_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def trusted_result_is_successful(self) -> AcquisitionResult:
        if self.verification_status is AcquisitionVerificationStatus.TRUSTED:
            if self.http_status < 200 or self.http_status >= 300:
                raise ValueError("trusted acquisition requires a successful HTTP response")
            expected_types = {
                ManufacturerDocumentType.BOUNDARY_SCAN_DESCRIPTION: {
                    "application/octet-stream",
                    "text/plain",
                }
            }.get(self.document_type, {"application/pdf"})
            if self.content_type not in expected_types:
                raise ValueError(
                    "trusted acquisition content type does not match the document type"
                )
        return self

    def provenance(self) -> ManufacturerAcquisitionProvenance:
        return ManufacturerAcquisitionProvenance(
            acquisition_id=self.acquisition_id,
            original_url=self.original_url,
            final_url=self.final_url,
            retrieved_at=self.retrieved_at,
            sha256=self.sha256,
            verification_status=self.verification_status,
        )


class AcquisitionChangeEvent(StrictModel):
    event_id: Identifier
    kind: AcquisitionChangeKind
    acquisition_id: Identifier
    original_url: NonEmptyString
    occurred_at: datetime = Field(default_factory=utc_now)
    previous_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AcquisitionCatalog(StrictModel):
    documents: list[AcquisitionResult] = Field(default_factory=list)
    events: list[AcquisitionChangeEvent] = Field(default_factory=list)


class AcquisitionFailure(StrictModel):
    request: AcquisitionRequest
    error: NonEmptyString


class AcquisitionBatchResult(StrictModel):
    acquired: list[AcquisitionResult] = Field(default_factory=list)
    failed: list[AcquisitionFailure] = Field(default_factory=list)
    ingestion_reports: list[dict[str, object]] = Field(default_factory=list)
