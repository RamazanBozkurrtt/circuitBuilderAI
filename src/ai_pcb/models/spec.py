from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel


class RequirementStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class Requirement(StrictModel):
    """A requirement whose unresolved state can never masquerade as a value."""

    status: RequirementStatus
    critical: bool
    value: JsonValue | None = None
    unit: str | None = None
    description: NonEmptyString
    rationale: str | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_resolution(self) -> Requirement:
        if self.status is RequirementStatus.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN requirements cannot contain a value")
        if self.status is RequirementStatus.RESOLVED and self.value is None:
            raise ValueError("RESOLVED requirements require an explicit value")
        return self


class RequirementSection(StrictModel):
    requirements: dict[Identifier, Requirement]


class ProjectMetadata(StrictModel):
    project_name: Identifier
    revision: NonEmptyString
    description: str | None = None
    author: str | None = None


class DesignIntent(StrictModel):
    """User-requested specialization IDs; dependencies are resolved separately."""

    specializations: list[Identifier] = Field(default_factory=lambda: ["generic"])


class MasterSpec(StrictModel):
    """Authoritative, user-maintained engineering requirement contract."""

    schema_version: NonEmptyString
    project: ProjectMetadata
    design: DesignIntent = Field(default_factory=DesignIntent)
    electrical: RequirementSection
    audio: RequirementSection
    processing: RequirementSection
    power: RequirementSection
    interfaces: RequirementSection
    mechanical: RequirementSection
    manufacturing: RequirementSection
    environmental: RequirementSection
    design_constraints: RequirementSection
    acceptance_criteria: RequirementSection

    @classmethod
    def empty_template(
        cls, project_name: str, *, specializations: list[str] | None = None
    ) -> MasterSpec:
        return cls(
            schema_version="1.1",
            project=ProjectMetadata(project_name=project_name, revision="0.1"),
            design=DesignIntent(specializations=specializations or ["generic"]),
            electrical=RequirementSection(requirements={}),
            audio=RequirementSection(requirements={}),
            processing=RequirementSection(requirements={}),
            power=RequirementSection(requirements={}),
            interfaces=RequirementSection(requirements={}),
            mechanical=RequirementSection(requirements={}),
            manufacturing=RequirementSection(requirements={}),
            environmental=RequirementSection(requirements={}),
            design_constraints=RequirementSection(requirements={}),
            acceptance_criteria=RequirementSection(requirements={}),
        )

    def sections(self) -> dict[str, RequirementSection]:
        return {
            name: getattr(self, name)
            for name in (
                "electrical",
                "audio",
                "processing",
                "power",
                "interfaces",
                "mechanical",
                "manufacturing",
                "environmental",
                "design_constraints",
                "acceptance_criteria",
            )
        }
