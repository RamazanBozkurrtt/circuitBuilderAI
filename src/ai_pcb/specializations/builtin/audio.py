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
    architecture_blocks=[
        ArchitectureBlockGuidance(
            role="microphone_front_end",
            required_capabilities=["low-noise multichannel audio input conditioning"],
            rationale="Audio inputs require an explicit electrical front end.",
            retrieval_hints=["microphone input noise bias interface"],
        ),
        ArchitectureBlockGuidance(
            role="audio_conversion",
            required_capabilities=["synchronized ADC and DAC conversion"],
            rationale="The audio signal chain requires evidenced converter capacity and quality.",
            retrieval_hints=["audio codec ADC DAC channels latency"],
        ),
        ArchitectureBlockGuidance(
            role="clocking",
            required_capabilities=["low-jitter synchronized audio clocks"],
            rationale="Converter and processor clock compatibility is a first-class concern.",
            retrieval_hints=["audio master clock jitter synchronization"],
        ),
    ],
    component_categories=[
        ComponentCategoryGuidance(
            category="ADC",
            required_facts=[
                "channel_count",
                "sample_rate",
                "bit_depth",
                "latency",
                "snr",
                "thd_n",
                "audio_interface",
                "clocking",
            ],
            retrieval_hints=["multichannel audio ADC latency SNR THD+N"],
        ),
        ComponentCategoryGuidance(
            category="DAC",
            required_facts=[
                "channel_count",
                "sample_rate",
                "bit_depth",
                "latency",
                "snr",
                "thd_n",
                "audio_interface",
                "clocking",
            ],
            retrieval_hints=["multichannel audio DAC latency SNR THD+N"],
        ),
        ComponentCategoryGuidance(
            category="AUDIO_CODEC",
            required_facts=[
                "input_channels",
                "output_channels",
                "sample_rate",
                "bit_depth",
                "adc_latency",
                "dac_latency",
                "snr",
                "thd_n",
                "audio_interface",
                "clocking",
            ],
            retrieval_hints=["multichannel audio codec ADC DAC latency"],
        ),
        ComponentCategoryGuidance(
            category="CLOCKING",
            required_facts=["output_frequencies", "jitter", "synchronization", "supply_voltage"],
            retrieval_hints=["audio clock generator jitter synchronization"],
        ),
    ],
    evaluation_criteria=[
        EvaluationCriterionGuidance(
            criterion_id="channel_capacity",
            dimension="channel capacity",
            applicable_categories=["ADC", "DAC", "AUDIO_CODEC"],
        ),
        EvaluationCriterionGuidance(
            criterion_id="audio_performance",
            dimension="audio performance",
            applicable_categories=["ADC", "DAC", "AUDIO_CODEC", "CLASS_D_AMPLIFIER"],
            default_weight=1.5,
        ),
        EvaluationCriterionGuidance(
            criterion_id="clock_interface_compatibility",
            dimension="clock and interface compatibility",
            applicable_categories=["ADC", "DAC", "AUDIO_CODEC", "CLOCKING"],
            default_weight=1.5,
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
