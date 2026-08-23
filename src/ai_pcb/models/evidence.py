from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ai_pcb.models.common import Identifier, NonEmptyString, TimestampedModel


class EvidenceSource(StrEnum):
    USER_SPEC = "USER_SPEC"
    DATASHEET = "DATASHEET"
    REFERENCE_DESIGN = "REFERENCE_DESIGN"
    APPLICATION_NOTE = "APPLICATION_NOTE"
    HARDWARE_REFERENCE = "HARDWARE_REFERENCE"
    EVALUATION_BOARD_GUIDE = "EVALUATION_BOARD_GUIDE"
    ERRATA = "ERRATA"
    SIMULATION = "SIMULATION"
    EDA_VALIDATION = "EDA_VALIDATION"
    RULE_ENGINE = "RULE_ENGINE"


class EvidenceProvenance(TimestampedModel):
    source: EvidenceSource
    manufacturer: str | None = None
    document: str | None = None
    revision: str | None = None
    page: str | None = None
    section: str | None = None
    locator: str | None = None
    source_url: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    acquisition_id: Identifier | None = None


class Evidence(TimestampedModel):
    evidence_id: Identifier
    title: NonEmptyString
    provenance: EvidenceProvenance
    extracted_content: NonEmptyString
    normalized_fact: NonEmptyString
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    artifact_path: str | None = None
