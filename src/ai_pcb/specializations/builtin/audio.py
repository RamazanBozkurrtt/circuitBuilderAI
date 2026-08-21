from ai_pcb.specializations.models import (
    AcceptanceCriterionExtension,
    CapabilityRequirement,
    DesignSpecialization,
    EngineeringCapability,
    EngineeringGuidance,
    EvidenceRequirement,
    RequirementDomain,
    SpecializationMetadata,
    ValidationDomain,
)

AUDIO = DesignSpecialization(
    id="audio",
    name="Audio PCB",
    version="1.0.0",
    description=(
        "Reusable audio conversion, signal-quality, clocking, interface, and supply concerns."
    ),
    extends=["mixed_signal"],
    requirement_domains=[RequirementDomain.AUDIO],
    validation_domains=[
        ValidationDomain.AUDIO,
        ValidationDomain.AUDIO_PERFORMANCE,
        ValidationDomain.CLOCKING,
    ],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.AUDIO_PERFORMANCE,
            applicable_stages=["SCHEMATIC_VERIFICATION", "PCB_VERIFICATION"],
            rationale="Audio suitability depends on measured or evidenced signal quality.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.CLOCK_ANALYSIS,
            applicable_stages=["SCHEMATIC_VERIFICATION", "PCB_VERIFICATION"],
            rationale="Converters and digital audio interfaces require valid synchronized clocks.",
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.AUDIO_PERFORMANCE,
            summary="Treat audio signal quality as a first-class engineering outcome.",
            concerns=[
                "ADC and DAC quality",
                "SNR, THD+N, noise, and dynamic range",
                "clipping and signal headroom",
                "codec performance",
                "analog signal integrity",
                "low-noise supplies",
                "audio interfaces",
                "channel matching and synchronization",
            ],
        ),
        EngineeringGuidance(
            domain=ValidationDomain.CLOCKING,
            summary="Verify audio clock generation, distribution, synchronization, and jitter.",
            concerns=[
                "master clock requirements",
                "sample synchronization",
                "jitter",
                "converter clock requirements",
                "clock distribution and routing",
            ],
        ),
    ],
    evidence_requirements=[
        EvidenceRequirement(
            domain=ValidationDomain.AUDIO_PERFORMANCE,
            description=(
                "Audio performance claims require datasheet conditions or measured evidence."
            ),
            preferred_source_types=["DATASHEET", "REFERENCE_DESIGN", "SIMULATION"],
        )
    ],
    acceptance_criteria_extensions=[
        AcceptanceCriterionExtension(
            domain=ValidationDomain.AUDIO_PERFORMANCE,
            description=(
                "Audio performance meets explicit SNR, THD+N, noise, range, and headroom "
                "requirements."
            ),
            future_validator="Audio Performance Validator",
        )
    ],
    metadata=SpecializationMetadata(
        tags=["audio", "mixed-signal"],
        retrieval_hints=[
            "audio codec",
            "ADC SNR THD+N",
            "DAC noise dynamic range",
            "audio clock jitter",
            "audio interface",
            "low-noise supply layout",
        ],
    ),
)
