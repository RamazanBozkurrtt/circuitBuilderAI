from ai_pcb.specializations.models import (
    CapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    SpecializationMetadata,
    ValidationDomain,
)

POWER_ELECTRONICS = DesignSpecialization(
    id="power_electronics",
    name="Power Electronics PCB",
    version="1.0.0",
    description=(
        "High-current, switching-loop, thermal, isolation, clearance, and derating concerns."
    ),
    extends=["generic"],
    validation_domains=[
        ValidationDomain.POWER_INTEGRITY,
        ValidationDomain.THERMAL,
        ValidationDomain.ISOLATION,
        ValidationDomain.EMI_EMC,
    ],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.POWER_INTEGRITY,
            applicable_stages=["SCHEMATIC_VERIFICATION", "PCB_VERIFICATION"],
            rationale="High-current paths and switching loops require deterministic review.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.THERMAL_ANALYSIS,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Losses and temperature rise must remain within evidenced limits.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.EMI_EMC_REVIEW,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Fast switching nodes require emissions and coupling review.",
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.POWER_INTEGRITY,
            summary="Minimize hazardous energy loops and validate current and voltage stress.",
            concerns=[
                "high-current paths and current density",
                "switching-loop area",
                "thermal management",
                "creepage and clearance",
                "isolation barriers",
                "component and conductor derating",
            ],
        )
    ],
    metadata=SpecializationMetadata(
        tags=["power-electronics"],
        retrieval_hints=[
            "switching loop",
            "current density",
            "thermal resistance",
            "creepage clearance isolation",
        ],
    ),
)
