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

AUDIO_ANC = DesignSpecialization(
    id="audio_anc",
    name="Real-Time Active Noise Cancellation",
    version="1.0.0",
    description=(
        "Deep ANC architecture, real-time processing, total-latency, audio, clock, and "
        "layout concerns."
    ),
    extends=["audio"],
    requirement_domains=[RequirementDomain.PROCESSING],
    validation_domains=[
        ValidationDomain.REAL_TIME_ANC,
        ValidationDomain.LATENCY,
        ValidationDomain.EMI_EMC,
    ],
    required_capabilities=[
        CapabilityRequirement(
            capability=EngineeringCapability.REAL_TIME_PROCESSING_ANALYSIS,
            applicable_stages=["ARCHITECTURE", "SCHEMATIC_VERIFICATION"],
            rationale=(
                "FxLMS and multichannel ANC must fit the real-time compute and buffering "
                "budget."
            ),
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.LATENCY_ANALYSIS,
            applicable_stages=["SCHEMATIC_VERIFICATION"],
            rationale="ANC suitability depends on total end-to-end path latency.",
        ),
        CapabilityRequirement(
            capability=EngineeringCapability.EMI_EMC_REVIEW,
            applicable_stages=["PCB_VERIFICATION"],
            rationale=(
                "Noise coupling can directly degrade microphone and cancellation performance."
            ),
        ),
    ],
    engineering_guidance=[
        EngineeringGuidance(
            domain=ValidationDomain.REAL_TIME_ANC,
            summary=(
                "Define an ANC signal chain and processing architecture that is viable in "
                "real time."
            ),
            concerns=[
                "reference and error microphone topology",
                "microphone and output/speaker channel counts",
                "ADC, DSP, DAC, and amplifier architecture",
                "channel synchronization",
                "real-time ANC and FxLMS",
                "multichannel and MIMO processing where required",
                "sample rate and bit depth",
                "computational budget, DSP headroom, and buffering",
            ],
        ),
        EngineeringGuidance(
            domain=ValidationDomain.LATENCY,
            summary="Budget and verify every contributor to total input-to-output latency.",
            concerns=[
                "ADC latency",
                "digital-interface latency",
                "buffering latency",
                "DSP processing latency",
                "DAC latency",
                "amplifier or acoustic-path delay where applicable",
                "total end-to-end latency and ANC suitability",
            ],
        ),
        EngineeringGuidance(
            domain=ValidationDomain.AUDIO_PERFORMANCE,
            summary="Preserve adequate sensing and output fidelity for cancellation performance.",
            concerns=[
                "SNR and THD+N",
                "ADC, DAC, microphone-preamp, and output noise",
                "dynamic range, clipping, and headroom",
                "channel matching",
            ],
        ),
        EngineeringGuidance(
            domain=ValidationDomain.EMI_EMC,
            summary=(
                "Protect low-level audio and timing paths through deliberate PCB implementation."
            ),
            concerns=[
                "analog and digital partitioning",
                "return-current paths and grounding",
                "low-noise power rails",
                "converter and microphone-front-end placement",
                "microphone-input and clock routing",
                "switching-regulator and amplifier coupling",
                "EMI and EMC behavior",
            ],
        ),
    ],
    evidence_requirements=[
        EvidenceRequirement(
            domain=ValidationDomain.LATENCY,
            description=(
                "Each latency budget term requires a documented source, model, or measurement."
            ),
            preferred_source_types=["DATASHEET", "REFERENCE_DESIGN", "SIMULATION"],
        ),
        EvidenceRequirement(
            domain=ValidationDomain.REAL_TIME_ANC,
            description="Processing capacity and algorithm assumptions require traceable support.",
            preferred_source_types=["DATASHEET", "APPLICATION_NOTE", "SIMULATION"],
        ),
    ],
    acceptance_criteria_extensions=[
        AcceptanceCriterionExtension(
            domain=ValidationDomain.LATENCY,
            description=(
                "Total end-to-end latency satisfies the explicit ANC requirement and includes "
                "every path term."
            ),
            future_validator="ANC Total Latency Validator",
        ),
        AcceptanceCriterionExtension(
            domain=ValidationDomain.REAL_TIME_ANC,
            description=(
                "The selected processing architecture has evidenced compute, memory, buffering, "
                "and headroom."
            ),
            future_validator="ANC Real-Time Processing Validator",
        ),
    ],
    metadata=SpecializationMetadata(
        tags=["audio", "anc", "real-time", "mixed-signal"],
        retrieval_hints=[
            "reference microphone error microphone",
            "codec ADC DAC DSP",
            "FxLMS MIMO ANC processing",
            "converter and DSP latency",
            "sample rate bit depth buffering",
            "audio clocking synchronization jitter",
            "microphone noise low-noise layout",
            "ANC layout recommendations",
        ],
    ),
)
