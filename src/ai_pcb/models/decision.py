from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, TimestampedModel


class DecisionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DecisionAlternative(TimestampedModel):
    name: NonEmptyString
    reason_not_selected: str | None = None


class DecisionTransition(TimestampedModel):
    from_status: DecisionStatus
    to_status: DecisionStatus
    reason: NonEmptyString


class EngineeringDecision(TimestampedModel):
    decision_id: Identifier
    title: NonEmptyString
    statement: NonEmptyString
    status: DecisionStatus = DecisionStatus.PROPOSED
    evidence_ids: list[Identifier] = Field(default_factory=list)
    validation_result_ids: list[Identifier] = Field(default_factory=list)
    alternatives: list[DecisionAlternative] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    history: list[DecisionTransition] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_support(self) -> EngineeringDecision:
        if (
            self.status in {DecisionStatus.EVIDENCE_VERIFIED, DecisionStatus.VALIDATED}
            and not self.evidence_ids
        ):
            raise ValueError(f"{self.status} decisions require evidence")
        if self.status is DecisionStatus.VALIDATED and not self.validation_result_ids:
            raise ValueError("VALIDATED decisions require validation results")
        return self
