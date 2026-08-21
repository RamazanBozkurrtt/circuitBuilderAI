from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, TimestampedModel
from ai_pcb.models.decision import DecisionStatus
from ai_pcb.models.spec import RequirementStatus
from ai_pcb.models.validation import ValidationSeverity, ValidationStatus


class ConstraintKind(StrEnum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    OPTIMIZATION_OBJECTIVE = "OPTIMIZATION_OBJECTIVE"


class ValueStatus(StrEnum):
    KNOWN = "KNOWN"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class InterfaceDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class ArchitectureReviewStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EngineeringValue(StrictModel):
    status: ValueStatus
    value: JsonValue | None = None
    unit: str | None = None
    conditions: list[str] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    assumption: str | None = None

    @model_validator(mode="after")
    def value_matches_status(self) -> EngineeringValue:
        if self.status is ValueStatus.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN engineering values cannot contain a value")
        if self.status is not ValueStatus.UNKNOWN and self.value is None:
            raise ValueError("known or estimated engineering values require a value")
        if self.status is ValueStatus.ESTIMATED and not self.assumption:
            raise ValueError("estimated engineering values require an explicit assumption")
        return self


class DerivedConstraint(StrictModel):
    constraint_id: Identifier
    description: NonEmptyString
    kind: ConstraintKind
    status: RequirementStatus
    value: JsonValue | None = None
    unit: str | None = None
    critical: bool = False
    source_requirements: list[Identifier] = Field(default_factory=list)
    declared_by_specializations: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def resolution_is_explicit(self) -> DerivedConstraint:
        if self.status is RequirementStatus.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN constraints cannot contain a value")
        if self.status is RequirementStatus.RESOLVED and self.value is None:
            raise ValueError("RESOLVED constraints require a value")
        return self


class BlockInterface(StrictModel):
    interface_id: Identifier
    name: NonEmptyString
    direction: InterfaceDirection
    interface_type: NonEmptyString
    channels: EngineeringValue
    clock_domain: str | None = None
    connected_block_id: Identifier | None = None
    constraints: list[DerivedConstraint] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)


class FunctionalBlock(StrictModel):
    block_id: Identifier
    role: Identifier
    name: NonEmptyString
    required_capabilities: list[NonEmptyString] = Field(default_factory=list)
    channel_requirements: list[DerivedConstraint] = Field(default_factory=list)
    interfaces: list[BlockInterface] = Field(default_factory=list)
    constraints: list[DerivedConstraint] = Field(default_factory=list)
    evidence_references: list[Identifier] = Field(default_factory=list)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    unresolved_requirements: list[DerivedConstraint] = Field(default_factory=list)


class ArchitectureConnection(StrictModel):
    connection_id: Identifier
    source_block_id: Identifier
    destination_block_id: Identifier
    interface_type: NonEmptyString
    latency_critical: bool = False
    synchronization_required: bool = False


class ArchitectureRisk(TimestampedModel):
    risk_id: Identifier
    description: NonEmptyString
    severity: ValidationSeverity
    affected_blocks: list[Identifier] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    mitigation: str | None = None
    unresolved: bool = True


class SystemArchitecture(StrictModel):
    architecture_id: Identifier
    name: NonEmptyString
    topology: NonEmptyString
    functional_blocks: list[FunctionalBlock] = Field(min_length=1)
    connections: list[ArchitectureConnection] = Field(default_factory=list)
    hard_constraints: list[DerivedConstraint] = Field(default_factory=list)
    optimization_objectives: list[DerivedConstraint] = Field(default_factory=list)
    risks: list[ArchitectureRisk] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    unresolved_requirements: list[DerivedConstraint] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_existing_blocks(self) -> SystemArchitecture:
        block_ids = {block.block_id for block in self.functional_blocks}
        if len(block_ids) != len(self.functional_blocks):
            raise ValueError("functional block identifiers must be unique")
        for connection in self.connections:
            if (
                connection.source_block_id not in block_ids
                or connection.destination_block_id not in block_ids
            ):
                raise ValueError("architecture connection references an unknown block")
        return self


class ArchitectureCriterionEvaluation(StrictModel):
    criterion_id: Identifier
    kind: ConstraintKind
    status: ValidationStatus
    rationale: NonEmptyString
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float = Field(default=1.0, ge=0.0)
    evidence_ids: list[Identifier] = Field(default_factory=list)


class ArchitectureEvaluation(StrictModel):
    evaluation_id: Identifier
    criteria: list[ArchitectureCriterionEvaluation] = Field(default_factory=list)
    viable: bool
    unresolved_trade_offs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def hard_failures_are_not_viable(self) -> ArchitectureEvaluation:
        hard_failure = any(
            item.kind is ConstraintKind.HARD_CONSTRAINT and item.status is ValidationStatus.FAIL
            for item in self.criteria
        )
        if hard_failure and self.viable:
            raise ValueError("an architecture with a failed hard constraint cannot be viable")
        return self


class ArchitectureCandidate(TimestampedModel):
    candidate_id: Identifier
    architecture: SystemArchitecture
    rationale: NonEmptyString
    evaluation: ArchitectureEvaluation
    supersedes_candidate_id: Identifier | None = None


class ArchitectureDecision(TimestampedModel):
    decision_id: Identifier
    selected_candidate_id: Identifier | None = None
    status: DecisionStatus = DecisionStatus.PROPOSED
    viable_alternative_ids: list[Identifier] = Field(default_factory=list)
    rejected_candidate_ids: list[Identifier] = Field(default_factory=list)
    rejection_reasons: list[NonEmptyString] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    risk_ids: list[Identifier] = Field(default_factory=list)
    unresolved_trade_offs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def selected_candidate_is_required(self) -> ArchitectureDecision:
        if self.status is not DecisionStatus.REJECTED and self.selected_candidate_id is None:
            raise ValueError("a current architecture decision requires a selected candidate")
        if (
            self.status in {DecisionStatus.EVIDENCE_VERIFIED, DecisionStatus.VALIDATED}
            and not self.evidence_ids
        ):
            raise ValueError("evidence-verified architecture decisions require evidence")
        if self.status is DecisionStatus.VALIDATED:
            raise ValueError("Phase 3 architecture decisions cannot be VALIDATED")
        return self


class ArchitectureReviewFinding(StrictModel):
    finding_id: Identifier
    status: ValidationStatus
    severity: ValidationSeverity
    category: Identifier
    description: NonEmptyString
    affected_ids: list[Identifier] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @property
    def blocks_acceptance(self) -> bool:
        return self.severity is ValidationSeverity.CRITICAL and self.status in {
            ValidationStatus.FAIL,
            ValidationStatus.UNKNOWN,
        }


class ArchitectureReview(TimestampedModel):
    review_id: Identifier
    candidate_id: Identifier
    attempt: int = Field(ge=1)
    status: ArchitectureReviewStatus
    findings: list[ArchitectureReviewFinding] = Field(default_factory=list)
    correction_target: Identifier | None = None

    @model_validator(mode="after")
    def status_matches_findings(self) -> ArchitectureReview:
        blocked = any(finding.blocks_acceptance for finding in self.findings)
        if blocked != (self.status is ArchitectureReviewStatus.REJECTED):
            raise ValueError("architecture review status must reflect blocking findings")
        if blocked and self.correction_target is None:
            raise ValueError("a rejected review requires a correction target")
        return self
