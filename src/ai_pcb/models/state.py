from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, TimestampedModel
from ai_pcb.models.decision import EngineeringDecision
from ai_pcb.models.spec import MasterSpec
from ai_pcb.models.validation import VerificationReport
from ai_pcb.specializations.builtin import builtin_registry
from ai_pcb.specializations.models import ResolvedSpecialization, ResolvedSpecializationContext
from ai_pcb.specializations.registry import specialization_reference


class WorkflowStage(StrEnum):
    SPECIFICATION = "SPECIFICATION"
    ARCHITECTURE = "ARCHITECTURE"
    COMPONENT_SELECTION = "COMPONENT_SELECTION"
    DATASHEET_ANALYSIS = "DATASHEET_ANALYSIS"
    SCHEMATIC = "SCHEMATIC"
    SCHEMATIC_VERIFICATION = "SCHEMATIC_VERIFICATION"
    PCB_LAYOUT = "PCB_LAYOUT"
    PCB_VERIFICATION = "PCB_VERIFICATION"
    MANUFACTURING = "MANUFACTURING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class StageArtifactStatus(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"


class StageArtifact(StrictModel):
    status: StageArtifactStatus
    payload: dict[str, JsonValue] | None = None
    note: NonEmptyString


class StateTransition(TimestampedModel):
    from_stage: WorkflowStage
    to_stage: WorkflowStage
    reason: NonEmptyString
    iteration: int = Field(ge=0)


class DesignState(TimestampedModel):
    schema_version: NonEmptyString = "1.1"
    project_name: Identifier
    master_spec: MasterSpec
    requested_specializations: list[Identifier] = Field(default_factory=list)
    resolved_specializations: list[ResolvedSpecialization] = Field(default_factory=list)
    workflow_stage: WorkflowStage = WorkflowStage.SPECIFICATION
    iteration: int = Field(default=0, ge=0)
    architecture: StageArtifact | None = None
    components: list[StageArtifact] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    decisions: list[EngineeringDecision] = Field(default_factory=list)
    verification_reports: list[VerificationReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    history: list[StateTransition] = Field(default_factory=list)

    @model_validator(mode="after")
    def project_names_match(self) -> DesignState:
        if self.project_name != self.master_spec.project.project_name:
            raise ValueError("DesignState and MASTER_SPEC project names must match")
        context = builtin_registry().resolve(self.master_spec.design.specializations)
        requested = context.requested
        resolved = [specialization_reference(item) for item in context.resolved]
        if self.requested_specializations and self.requested_specializations != requested:
            raise ValueError("requested specializations must match MASTER_SPEC design intent")
        if self.resolved_specializations and [
            item.id for item in self.resolved_specializations
        ] != [item.id for item in resolved]:
            raise ValueError("resolved specialization dependency order is invalid")
        object.__setattr__(self, "requested_specializations", requested)
        if not self.resolved_specializations:
            object.__setattr__(self, "resolved_specializations", resolved)
        return self

    def specialization_context(self) -> ResolvedSpecializationContext:
        """Rebuild and verify the declarative context against the stored snapshot."""

        context = builtin_registry().resolve(self.requested_specializations)
        references = [specialization_reference(item) for item in context.resolved]
        if references != self.resolved_specializations:
            raise ValueError("stored specialization snapshot differs from current definitions")
        return context
