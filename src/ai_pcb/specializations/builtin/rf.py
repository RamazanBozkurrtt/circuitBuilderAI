from ai_pcb.specializations.models import (
    CapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    SpecializationMetadata,
    ValidationDomain,
)

RF = DesignSpecialization(
    id="rf",
    name="RF PCB",
    version="1.0.0",
    description="RF transmission, matching, antenna, grounding, shielding, and layout concerns.",
    extends=["mixed_signal"],
    validation_domains=[ValidationDomain.RF, ValidationDomain.EMI_EMC],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.RF_ANALYSIS,
            applicable_stages=["SCHEMATIC_VERIFICATION", "PCB_VERIFICATION"],
            rationale="RF matching and transmission structures require frequency-domain analysis.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.EMI_EMC_REVIEW,
            applicable_stages=["PCB_VERIFICATION"],
            rationale="RF energy containment, shielding, and coupling require review.",
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.RF,
            summary="Preserve intended RF impedance and field containment from source to load.",
            concerns=[
                "controlled impedance and transmission lines",
                "RF matching networks",
                "antenna placement and keep-outs",
                "grounding and via fences",
                "shielding",
                "RF component placement and routing",
            ],
        )
    ],
    metadata=SpecializationMetadata(
        tags=["rf", "mixed-signal"],
        retrieval_hints=[
            "RF matching",
            "transmission line",
            "antenna layout",
            "grounding shielding",
        ],
    ),
)
