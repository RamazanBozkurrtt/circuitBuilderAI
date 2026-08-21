from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.architecture import ConstraintKind, EngineeringValue
from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, TimestampedModel
from ai_pcb.models.decision import DecisionStatus
from ai_pcb.models.spec import RequirementStatus
from ai_pcb.models.validation import ValidationStatus


class ComponentCategory(StrEnum):
    DSP_PROCESSOR = "DSP_PROCESSOR"
    ADC = "ADC"
    DAC = "DAC"
    AUDIO_CODEC = "AUDIO_CODEC"
    CLASS_D_AMPLIFIER = "CLASS_D_AMPLIFIER"
    CLOCKING = "CLOCKING"
    POWER_MANAGEMENT = "POWER_MANAGEMENT"


class CandidateEvidenceStatus(StrEnum):
    IDENTITY_KNOWN = "IDENTITY_KNOWN"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"


class CandidateViability(StrEnum):
    VIABLE = "VIABLE"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    REJECTED = "REJECTED"


class EvidenceAcquisitionStatus(StrEnum):
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    ACQUIRED = "ACQUIRED"


class ComponentRequirement(StrictModel):
    requirement_id: Identifier
    category: ComponentCategory
    attribute: Identifier
    description: NonEmptyString
    kind: ConstraintKind
    status: RequirementStatus
    value: JsonValue | None = None
    unit: str | None = None
    critical: bool = False
    source_requirements: list[Identifier] = Field(default_factory=list)
    declared_by_specializations: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_unknown(self) -> ComponentRequirement:
        if self.status is RequirementStatus.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN component requirements cannot contain a value")
        if self.status is RequirementStatus.RESOLVED and self.value is None:
            raise ValueError("RESOLVED component requirements require a value")
        return self


class ComponentFact(StrictModel):
    attribute: Identifier
    value: EngineeringValue


class ComponentCandidate(TimestampedModel):
    candidate_id: Identifier
    category: ComponentCategory
    manufacturer: NonEmptyString
    part_number: NonEmptyString
    evidence_status: CandidateEvidenceStatus
    identity_source_ids: list[Identifier] = Field(min_length=1)
    verified_evidence_ids: list[Identifier] = Field(default_factory=list)
    facts: list[ComponentFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_candidates_have_promoted_evidence(self) -> ComponentCandidate:
        if (
            self.evidence_status is CandidateEvidenceStatus.EVIDENCE_VERIFIED
            and not self.verified_evidence_ids
        ):
            raise ValueError("evidence-verified candidates require promoted evidence")
        return self


class ComponentCriterionEvaluation(StrictModel):
    criterion_id: Identifier
    dimension: NonEmptyString
    kind: ConstraintKind
    status: ValidationStatus
    rationale: NonEmptyString
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0)
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def scored_status_is_resolved(self) -> ComponentCriterionEvaluation:
        if (
            self.status in {ValidationStatus.UNKNOWN, ValidationStatus.NOT_APPLICABLE}
            and self.score is not None
        ):
            raise ValueError("unknown or inapplicable criteria cannot receive a score")
        return self


class ComponentEvaluation(StrictModel):
    evaluation_id: Identifier
    candidate_id: Identifier
    criteria: list[ComponentCriterionEvaluation] = Field(min_length=1)
    viability: CandidateViability
    weighted_optimization_score: float | None = Field(default=None, ge=0.0, le=1.0)
    rejection_reasons: list[NonEmptyString] = Field(default_factory=list)
    unresolved_trade_offs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def hard_constraints_dominate_scoring(self) -> ComponentEvaluation:
        hard_failures = [
            item
            for item in self.criteria
            if item.kind is ConstraintKind.HARD_CONSTRAINT and item.status is ValidationStatus.FAIL
        ]
        hard_unknowns = [
            item
            for item in self.criteria
            if item.kind is ConstraintKind.HARD_CONSTRAINT
            and item.status is ValidationStatus.UNKNOWN
        ]
        if hard_failures and self.viability is not CandidateViability.REJECTED:
            raise ValueError("failed hard constraints require candidate rejection")
        if not hard_failures and hard_unknowns and self.viability is CandidateViability.VIABLE:
            raise ValueError("unknown hard constraints require evidence before viability")
        if self.viability is CandidateViability.REJECTED and not self.rejection_reasons:
            raise ValueError("rejected candidates require rejection reasons")
        return self


class ComponentSelection(TimestampedModel):
    selection_id: Identifier
    category: ComponentCategory
    selected_candidate_id: Identifier | None = None
    status: DecisionStatus = DecisionStatus.PROPOSED
    viable_alternative_ids: list[Identifier] = Field(default_factory=list)
    rejected_candidate_ids: list[Identifier] = Field(default_factory=list)
    rejection_reasons: list[NonEmptyString] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    unresolved_trade_offs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def phase3_selection_lifecycle(self) -> ComponentSelection:
        if self.status is DecisionStatus.VALIDATED:
            raise ValueError("component selections cannot be VALIDATED in Phase 3")
        if self.status is DecisionStatus.EVIDENCE_VERIFIED and not self.evidence_ids:
            raise ValueError("evidence-verified component selections require evidence")
        return self


class EvidenceAcquisitionRequirement(TimestampedModel):
    requirement_id: Identifier
    category: ComponentCategory
    status: EvidenceAcquisitionStatus = EvidenceAcquisitionStatus.EVIDENCE_REQUIRED
    part_number: str | None = None
    manufacturer: str | None = None
    required_facts: list[Identifier] = Field(min_length=1)
    preferred_source_types: list[NonEmptyString] = Field(default_factory=list)
    reason: NonEmptyString
    blocking: bool = True
    acquired_evidence_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def acquisition_status_has_support(self) -> EvidenceAcquisitionRequirement:
        if self.status is EvidenceAcquisitionStatus.ACQUIRED and not self.acquired_evidence_ids:
            raise ValueError("acquired evidence requirements require evidence identifiers")
        return self


class ManufacturerComponentFact(StrictModel):
    fact_id: Identifier
    candidate_category: ComponentCategory
    candidate_manufacturer: NonEmptyString
    candidate_part_number: NonEmptyString
    attribute: Identifier
    value: JsonValue
    unit: str | None = None
    conditions: list[NonEmptyString] = Field(default_factory=list)
    acquisition_id: Identifier
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    evidence_text: NonEmptyString
    normalized_fact: NonEmptyString


class ManufacturerComponentFactCatalog(StrictModel):
    facts: list[ManufacturerComponentFact] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fact_ids(self) -> ManufacturerComponentFactCatalog:
        identifiers = [fact.fact_id for fact in self.facts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("manufacturer component fact identifiers must be unique")
        return self
