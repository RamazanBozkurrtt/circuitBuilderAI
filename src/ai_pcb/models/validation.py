from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, TimestampedModel
from ai_pcb.specializations.models import EngineeringCapability


class ValidationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidatorApplicability(StrictModel):
    """Declarative validator selection metadata; empty specialization/stage lists mean all."""

    applicable_specializations: list[Identifier] = Field(default_factory=list)
    applicable_stages: list[Identifier] = Field(default_factory=list)
    required_capability: EngineeringCapability | None = None


class ValidationResult(TimestampedModel):
    result_id: Identifier
    validator: Identifier
    status: ValidationStatus
    severity: ValidationSeverity
    summary: NonEmptyString
    details: list[str] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @property
    def blocks_progression(self) -> bool:
        return self.severity is ValidationSeverity.CRITICAL and self.status in {
            ValidationStatus.FAIL,
            ValidationStatus.UNKNOWN,
        }


class VerificationReport(TimestampedModel):
    report_id: Identifier
    stage: Identifier
    results: list[ValidationResult] = Field(min_length=1)
    can_advance: bool

    @model_validator(mode="after")
    def verify_advance_flag(self) -> VerificationReport:
        computed = not any(result.blocks_progression for result in self.results)
        if self.can_advance != computed:
            raise ValueError("can_advance must be derived from blocking validation results")
        return self
