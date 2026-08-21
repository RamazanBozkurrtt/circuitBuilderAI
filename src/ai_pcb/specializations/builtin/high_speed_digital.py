from ai_pcb.specializations.models import (
    CapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    SpecializationMetadata,
    ValidationDomain,
)

HIGH_SPEED_DIGITAL = DesignSpecialization(
    id="high_speed_digital",
    name="High-Speed Digital PCB",
    version="1.0.0",
    description="Digital interconnect timing, impedance, stack-up, and return-path concerns.",
    extends=["generic"],
    validation_domains=[ValidationDomain.HIGH_SPEED_DIGITAL, ValidationDomain.SIGNAL_INTEGRITY],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.SIGNAL_INTEGRITY,
            applicable_stages=["SCHEMATIC_VERIFICATION", "PCB_VERIFICATION"],
            rationale="High-speed interfaces require topology, timing, and interconnect analysis.",
        )
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.HIGH_SPEED_DIGITAL,
            summary="Treat interconnect geometry and return paths as part of circuit behavior.",
            concerns=[
                "controlled impedance and stack-up",
                "differential pairs",
                "continuous return paths",
                "length matching and timing",
                "via transitions and reference-plane changes",
            ],
        )
    ],
    metadata=SpecializationMetadata(
        tags=["high-speed", "digital"],
        retrieval_hints=[
            "controlled impedance",
            "differential pair",
            "length matching",
            "via transition",
        ],
    ),
)
