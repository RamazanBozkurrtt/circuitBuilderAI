from ai_pcb.specializations.models import (
    CapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    SpecializationMetadata,
    ValidationDomain,
)

MIXED_SIGNAL = DesignSpecialization(
    id="mixed_signal",
    name="Mixed-Signal PCB",
    version="1.0.0",
    description=(
        "Analog/digital boundary, converter, reference, return-current, and noise concerns."
    ),
    extends=["generic"],
    validation_domains=[ValidationDomain.MIXED_SIGNAL, ValidationDomain.SIGNAL_INTEGRITY],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.SIGNAL_INTEGRITY,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Mixed-signal return paths and coupling require layout-aware analysis.",
        )
    ],
    optional_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.SPICE,
            applicable_stages=["SCHEMATIC_VERIFICATION"],
            rationale="Analog paths may benefit from circuit simulation.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.EMI_EMC_REVIEW,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="Coupled analog/digital energy may require EMI/EMC review.",
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.MIXED_SIGNAL,
            summary="Control mixed-signal boundaries and preserve intended current paths.",
            concerns=[
                "analog and digital partitioning",
                "converter placement",
                "voltage and current references",
                "return-current paths",
                "digital and switching noise coupling",
            ],
        )
    ],
    metadata=SpecializationMetadata(
        tags=["mixed-signal"],
        retrieval_hints=[
            "converter layout",
            "reference bypassing",
            "return current",
            "noise coupling",
        ],
    ),
)
