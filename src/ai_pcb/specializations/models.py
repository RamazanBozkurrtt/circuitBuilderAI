from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel


class RequirementDomain(StrEnum):
    ELECTRICAL = "electrical"
    AUDIO = "audio"
    PROCESSING = "processing"
    POWER = "power"
    INTERFACES = "interfaces"
    MECHANICAL = "mechanical"
    MANUFACTURING = "manufacturing"
    ENVIRONMENTAL = "environmental"
    DESIGN_CONSTRAINTS = "design_constraints"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"


class ValidationDomain(StrEnum):
    ARCHITECTURE = "architecture"
    DATASHEET = "datasheet"
    ELECTRICAL_RATINGS = "electrical_ratings"
    POWER = "power"
    INTERFACES = "interfaces"
    MECHANICAL = "mechanical"
    THERMAL = "thermal"
    MANUFACTURING = "manufacturing"
    EVIDENCE_TRACEABILITY = "evidence_traceability"
    MIXED_SIGNAL = "mixed_signal"
    SIGNAL_INTEGRITY = "signal_integrity"
    POWER_INTEGRITY = "power_integrity"
    HIGH_SPEED_DIGITAL = "high_speed_digital"
    AUDIO = "audio"
    AUDIO_PERFORMANCE = "audio_performance"
    REAL_TIME_ANC = "real_time_anc"
    LATENCY = "latency"
    CLOCKING = "clocking"
    EMI_EMC = "emi_emc"
    RF = "rf"
    ISOLATION = "isolation"


class EngineeringCapability(StrEnum):
    DATASHEET_RETRIEVAL = "DATASHEET_RETRIEVAL"
    DATASHEET_VALIDATION = "DATASHEET_VALIDATION"
    EVIDENCE_TRACEABILITY = "EVIDENCE_TRACEABILITY"
    ARCHITECTURE_ANALYSIS = "ARCHITECTURE_ANALYSIS"
    COMPONENT_SELECTION = "COMPONENT_SELECTION"
    ERC = "ERC"
    DRC = "DRC"
    SPICE = "SPICE"
    SIGNAL_INTEGRITY = "SIGNAL_INTEGRITY"
    POWER_INTEGRITY = "POWER_INTEGRITY"
    THERMAL_ANALYSIS = "THERMAL_ANALYSIS"
    AUDIO_PERFORMANCE = "AUDIO_PERFORMANCE"
    LATENCY_ANALYSIS = "LATENCY_ANALYSIS"
    CLOCK_ANALYSIS = "CLOCK_ANALYSIS"
    REAL_TIME_PROCESSING_ANALYSIS = "REAL_TIME_PROCESSING_ANALYSIS"
    RF_ANALYSIS = "RF_ANALYSIS"
    EMI_EMC_REVIEW = "EMI_EMC_REVIEW"
    MANUFACTURING_VALIDATION = "MANUFACTURING_VALIDATION"


class CapabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    REQUIRED_BUT_UNAVAILABLE = "REQUIRED_BUT_UNAVAILABLE"
    OPTIONAL_UNAVAILABLE = "OPTIONAL_UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CapabilityRequirement(StrictModel):
    capability: EngineeringCapability
    applicable_stages: list[Identifier] = Field(min_length=1)
    rationale: NonEmptyString


class EvidenceRequirement(StrictModel):
    domain: ValidationDomain
    description: NonEmptyString
    preferred_source_types: list[NonEmptyString] = Field(default_factory=list)


class AcceptanceCriterionExtension(StrictModel):
    domain: ValidationDomain
    description: NonEmptyString
    future_validator: NonEmptyString | None = None


class EngineeringGuidance(StrictModel):
    domain: ValidationDomain
    summary: NonEmptyString
    concerns: list[NonEmptyString] = Field(min_length=1)


class ArchitectureBlockGuidance(StrictModel):
    """A declarative block concern; the synthesizer decides topology and applicability."""

    role: Identifier
    required_capabilities: list[NonEmptyString] = Field(default_factory=list)
    rationale: NonEmptyString
    retrieval_hints: list[NonEmptyString] = Field(default_factory=list)


class ComponentCategoryGuidance(StrictModel):
    category: Identifier
    required_facts: list[Identifier] = Field(default_factory=list)
    retrieval_hints: list[NonEmptyString] = Field(default_factory=list)


class EvaluationCriterionGuidance(StrictModel):
    criterion_id: Identifier
    dimension: NonEmptyString
    applicable_categories: list[Identifier] = Field(default_factory=list)
    default_weight: float = Field(default=1.0, ge=0.0)


class SpecializationMetadata(StrictModel):
    tags: list[Identifier] = Field(default_factory=list)
    retrieval_hints: list[NonEmptyString] = Field(default_factory=list)
    maturity: NonEmptyString = "declarative-foundation"


class DesignSpecialization(StrictModel):
    """Declarative specialization definition; it contains no executable hooks."""

    id: Identifier
    name: NonEmptyString
    version: NonEmptyString
    description: NonEmptyString
    extends: list[Identifier] = Field(default_factory=list)
    conflicts: list[Identifier] = Field(default_factory=list)
    requirement_domains: list[RequirementDomain] = Field(default_factory=list)
    validation_domains: list[ValidationDomain] = Field(default_factory=list)
    required_capabilities: list[CapabilityRequirement] = Field(default_factory=list)
    optional_capabilities: list[CapabilityRequirement] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)
    acceptance_criteria_extensions: list[AcceptanceCriterionExtension] = Field(default_factory=list)
    engineering_guidance: list[EngineeringGuidance] = Field(default_factory=list)
    architecture_blocks: list[ArchitectureBlockGuidance] = Field(default_factory=list)
    component_categories: list[ComponentCategoryGuidance] = Field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterionGuidance] = Field(default_factory=list)
    metadata: SpecializationMetadata = Field(default_factory=SpecializationMetadata)

    @model_validator(mode="after")
    def validate_relationships(self) -> DesignSpecialization:
        if self.id in self.extends:
            raise ValueError("a specialization cannot extend itself")
        if self.id in self.conflicts:
            raise ValueError("a specialization cannot conflict with itself")
        if set(self.extends) & set(self.conflicts):
            raise ValueError("a dependency cannot also be a conflict")
        return self


class ResolvedSpecialization(StrictModel):
    id: Identifier
    version: NonEmptyString
    definition_fingerprint: NonEmptyString


class AggregatedCapabilityRequirement(StrictModel):
    capability: EngineeringCapability
    required: bool
    applicable_stages: list[Identifier]
    declared_by: list[Identifier]
    rationales: list[NonEmptyString]


class ResolvedSpecializationContext(StrictModel):
    requested: list[Identifier]
    resolved: list[DesignSpecialization]
    requirement_domains: list[RequirementDomain]
    validation_domains: list[ValidationDomain]
    capabilities: list[AggregatedCapabilityRequirement]
    engineering_guidance: list[EngineeringGuidance]
    architecture_blocks: list[ArchitectureBlockGuidance]
    component_categories: list[ComponentCategoryGuidance]
    evaluation_criteria: list[EvaluationCriterionGuidance]
    evidence_requirements: list[EvidenceRequirement]
    acceptance_criteria_extensions: list[AcceptanceCriterionExtension]
    retrieval_hints: list[NonEmptyString]

    @property
    def resolved_ids(self) -> list[str]:
        return [specialization.id for specialization in self.resolved]


class CapabilityAssessment(StrictModel):
    capability: EngineeringCapability
    status: CapabilityStatus
    required: bool
    applicable_stages: list[Identifier]
    declared_by: list[Identifier]

    @property
    def blocks_stage(self) -> bool:
        return self.status is CapabilityStatus.REQUIRED_BUT_UNAVAILABLE


class CapabilityReport(StrictModel):
    stage: Identifier
    assessments: list[CapabilityAssessment]

    @property
    def missing_required(self) -> list[EngineeringCapability]:
        return [
            item.capability
            for item in self.assessments
            if item.status is CapabilityStatus.REQUIRED_BUT_UNAVAILABLE
        ]
