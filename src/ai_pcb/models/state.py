from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel, TimestampedModel
from ai_pcb.models.decision import EngineeringDecision
from ai_pcb.models.spec import MasterSpec
from ai_pcb.models.validation import VerificationReport


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
    schema_version: NonEmptyString = "1.0"
    project_name: Identifier
    master_spec: MasterSpec
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
        return self
