from ai_pcb.specializations.models import (
    AcceptanceCriterionExtension,
    ArchitectureBlockGuidance,
    CapabilityRequirement,
    ComponentCategoryGuidance,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    EvaluationCriterionGuidance,
    EvidenceRequirement,
    RequirementDomain,
    SpecializationMetadata,
    ValidationDomain,
)

GENERIC = DesignSpecialization(
    id="generic",
    name="Generic PCB Engineering Core",
    version="1.0.0",
    description=(
        "Universal electrical, evidence, physical, and manufacturing concerns for every PCB."
    ),
    requirement_domains=[
        RequirementDomain.ELECTRICAL,
        RequirementDomain.POWER,
        RequirementDomain.INTERFACES,
        RequirementDomain.MECHANICAL,
        RequirementDomain.MANUFACTURING,
        RequirementDomain.ENVIRONMENTAL,
        RequirementDomain.DESIGN_CONSTRAINTS,
        RequirementDomain.ACCEPTANCE_CRITERIA,
    ],
    validation_domains=[
        ValidationDomain.ARCHITECTURE,
        ValidationDomain.DATASHEET,
        ValidationDomain.ELECTRICAL_RATINGS,
        ValidationDomain.POWER,
        ValidationDomain.INTERFACES,
        ValidationDomain.MECHANICAL,
        ValidationDomain.THERMAL,
        ValidationDomain.MANUFACTURING,
        ValidationDomain.EVIDENCE_TRACEABILITY,
    ],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.DATASHEET_RETRIEVAL,
            applicable_stages=["DATASHEET_ANALYSIS"],
            rationale="Engineering evidence must be retrievable with source provenance.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.EVIDENCE_TRACEABILITY,
            applicable_stages=["SPECIFICATION", "DATASHEET_ANALYSIS"],
            rationale="Engineering facts and decisions must retain resolvable provenance.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.ARCHITECTURE_ANALYSIS,
            applicable_stages=["ARCHITECTURE"],
            rationale="Architecture claims require an explicit engineering review.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.COMPONENT_SELECTION,
            applicable_stages=["COMPONENT_SELECTION"],
            rationale="Parts must be selected against requirements and ratings.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.DATASHEET_VALIDATION,
            applicable_stages=["DATASHEET_ANALYSIS"],
            rationale="Component constraints must be validated against source documents.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.ERC,
            applicable_stages=["SCHEMATIC_VERIFICATION"],
            rationale="Schematic electrical-rule verification is universal.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.DRC,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="PCB design-rule verification is universal.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.MANUFACTURING_VALIDATION,
            applicable_stages=["MANUFACTURING"],
            rationale="Manufacturing outputs must be checked before release.",
        ),
    ],
    optional_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.POWER_INTEGRITY,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Power integrity depth depends on the board's current and noise constraints.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.THERMAL_ANALYSIS,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Thermal analysis applies when dissipation or environment demands it.",
        ),
    ],
    evidence_requirements=[
        EvidenceRequirement(
            domain=ValidationDomain.DATASHEET,
            description=(
                "Ratings, pin behavior, and operating limits require manufacturer evidence."
            ),
            preferred_source_types=["DATASHEET", "APPLICATION_NOTE", "REFERENCE_DESIGN"],
        )
    ],
    acceptance_criteria_extensions=[
        AcceptanceCriterionExtension(
            domain=ValidationDomain.EVIDENCE_TRACEABILITY,
            description="Critical claims and validated decisions have resolvable evidence.",
        ),
        AcceptanceCriterionExtension(
            domain=ValidationDomain.MANUFACTURING,
            description=(
                "ERC, DRC, mechanical, and manufacturing checks are explicit before release."
            ),
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.ELECTRICAL_RATINGS,
            summary="Verify universal PCB correctness before domain optimization.",
            concerns=[
                "electrical ratings and derating",
                "power and interface compatibility",
                "mechanical and environmental constraints",
                "thermal applicability",
                "ERC and DRC expectations",
                "manufacturing constraints",
                "component lifecycle and provenance where available",
            ],
        )
    ],
    architecture_blocks=[
        ArchitectureBlockGuidance(
            role="power_management",
            required_capabilities=["safe rail generation", "power sequencing where required"],
            rationale="Every active board requires an explicit power architecture.",
            retrieval_hints=["recommended operating conditions", "power sequencing"],
        ),
        ArchitectureBlockGuidance(
            role="programming_debug",
            required_capabilities=["bring-up and firmware development access"],
            rationale="Programmable devices need an explicit, possibly unresolved, debug path.",
        ),
        ArchitectureBlockGuidance(
            role="protection",
            required_capabilities=["interface and supply protection as requirements demand"],
            rationale="Protection applicability must be considered rather than silently omitted.",
        ),
    ],
    component_categories=[
        ComponentCategoryGuidance(
            category="POWER_MANAGEMENT",
            required_facts=[
                "input_voltage_range",
                "output_voltage",
                "output_current",
                "efficiency",
                "thermal_limits",
            ],
            retrieval_hints=["power management input voltage efficiency thermal"],
        )
    ],
    evaluation_criteria=[
        EvaluationCriterionGuidance(
            criterion_id="functional_compatibility",
            dimension="functional compatibility",
        ),
        EvaluationCriterionGuidance(
            criterion_id="power_requirements",
            dimension="power requirements",
        ),
        EvaluationCriterionGuidance(
            criterion_id="thermal_implications",
            dimension="thermal implications",
        ),
        EvaluationCriterionGuidance(
            criterion_id="package_complexity",
            dimension="package and PCB complexity",
            default_weight=0.5,
        ),
        EvaluationCriterionGuidance(
            criterion_id="evidence_completeness",
            dimension="evidence completeness",
        ),
        EvaluationCriterionGuidance(
            criterion_id="lifecycle_confidence",
            dimension="lifecycle and manufacturer confidence",
            default_weight=0.5,
        ),
    ],
    metadata=SpecializationMetadata(
        tags=["pcb", "universal"],
        retrieval_hints=[
            "absolute maximum ratings",
            "recommended operating conditions",
            "layout guidelines",
            "manufacturing constraints",
        ],
    ),
)
