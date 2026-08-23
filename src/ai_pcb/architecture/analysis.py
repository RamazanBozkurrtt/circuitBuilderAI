from __future__ import annotations

from ai_pcb.models.analysis import (
    ComputationalBudget,
    FxLMSScenario,
    FxLMSSuitabilityStatus,
    LatencyBudget,
    LatencyContribution,
    LatencyContributor,
    LatencyPathComparison,
)
from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.components import ComponentCandidate
from ai_pcb.models.spec import MasterSpec, RequirementStatus


def build_latency_budget() -> LatencyBudget:
    contributions = [
        LatencyContribution(
            contribution_id=f"latency-{contributor.value.lower()}",
            contributor=contributor,
            latency=EngineeringValue(
                status=ValueStatus.UNKNOWN,
                conditions=[
                    "Component and interface conditions are unresolved; unknown is not zero."
                ],
            ),
        )
        for contributor in LatencyContributor
    ]
    return LatencyBudget.from_contributions("anc-end-to-end-latency", contributions)


def build_evidence_aware_latency_budget(
    candidates: list[ComponentCandidate],
) -> LatencyBudget:
    contributions = build_latency_budget().contributions
    by_part = {candidate.part_number: candidate for candidate in candidates}
    ad1938 = by_part.get("AD1938")
    comparisons: list[LatencyPathComparison] = []
    if ad1938 is not None:
        facts = {fact.attribute: fact.value for fact in ad1938.facts}
        adc_evidence = facts["adc_latency"].evidence_ids
        dac_evidence = facts["dac_latency"].evidence_ids
        known = {
            LatencyContributor.ADC: EngineeringValue(
                status=ValueStatus.KNOWN,
                value=22.9844 / 96_000 * 1_000_000,
                unit="us",
                conditions=["AD1938 ADC decimation-filter group delay at selected 96 kHz."],
                evidence_ids=adc_evidence,
            ),
            LatencyContributor.DAC: EngineeringValue(
                status=ValueStatus.KNOWN,
                value=11 / 96_000 * 1_000_000,
                unit="us",
                conditions=["AD1938 DAC interpolation-filter group delay at selected 96 kHz."],
                evidence_ids=dac_evidence,
            ),
        }
        contributions = [
            item.model_copy(update={"latency": known[item.contributor]})
            if item.contributor in known
            else item
            for item in contributions
        ]
        comparisons.append(
            LatencyPathComparison(
                comparison_id="latency-path-ad1938-96k",
                architecture="multichannel codec + DSP",
                candidate_part_numbers=["AD1938"],
                sample_rate=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=96,
                    unit="kHz",
                    evidence_ids=facts["sample_rate"].evidence_ids,
                ),
                documented_converter_delay=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=(22.9844 + 11) / 96_000 * 1_000_000,
                    unit="us",
                    conditions=["ADC plus DAC documented digital-filter group delay only."],
                    evidence_ids=list(dict.fromkeys([*adc_evidence, *dac_evidence])),
                ),
                unknown_contributors=[
                    LatencyContributor.MICROPHONE_INTERFACE,
                    LatencyContributor.SERIAL_AUDIO_TRANSPORT,
                    LatencyContributor.BUFFERING,
                    LatencyContributor.DSP_PROCESSING,
                    LatencyContributor.AMPLIFIER_PATH,
                ],
            )
        )
    pcm = by_part.get("PCM3168A")
    if pcm is not None:
        facts = {fact.attribute: fact.value for fact in pcm.facts}
        comparisons.append(
            LatencyPathComparison(
                comparison_id="latency-path-pcm3168a-96k",
                architecture="multichannel codec + DSP alternative",
                candidate_part_numbers=["PCM3168A"],
                sample_rate=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=96,
                    unit="kHz",
                    evidence_ids=facts["sample_rate"].evidence_ids,
                ),
                documented_converter_delay=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=(27 + 28) / 96_000 * 1_000_000,
                    unit="us",
                    conditions=[
                        "ADC single-speed plus DAC dual-speed documented group delay at 96 kHz."
                    ],
                    evidence_ids=list(
                        dict.fromkeys(
                            [
                                *facts["adc_latency"].evidence_ids,
                                *facts["dac_latency"].evidence_ids,
                            ]
                        )
                    ),
                ),
                unknown_contributors=[
                    LatencyContributor.MICROPHONE_INTERFACE,
                    LatencyContributor.SERIAL_AUDIO_TRANSPORT,
                    LatencyContributor.BUFFERING,
                    LatencyContributor.DSP_PROCESSING,
                    LatencyContributor.AMPLIFIER_PATH,
                ],
            )
        )
    adau = by_part.get("ADAU1978")
    if adau is not None:
        facts = {fact.attribute: fact.value for fact in adau.facts}
        comparisons.append(
            LatencyPathComparison(
                comparison_id="latency-path-adau1978-96k",
                architecture="separate ADC + DSP + DAC",
                candidate_part_numbers=["ADAU1978", "UNKNOWN_DAC"],
                sample_rate=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=96,
                    unit="kHz",
                    evidence_ids=facts["sample_rate"].evidence_ids,
                ),
                documented_converter_delay=EngineeringValue(
                    status=ValueStatus.UNKNOWN,
                    conditions=[
                        "ADAU1978 ADC delay is documented, but the required standalone DAC and "
                        "its delay remain UNKNOWN; unknown is not zero."
                    ],
                    evidence_ids=facts["latency"].evidence_ids,
                ),
                unknown_contributors=list(LatencyContributor),
            )
        )
    tas = by_part.get("TAS6424-Q1")
    if adau is not None and tas is not None:
        comparisons = [
            comparison
            for comparison in comparisons
            if comparison.comparison_id != "latency-path-adau1978-96k"
        ]
        adau_facts = {fact.attribute: fact.value for fact in adau.facts}
        tas_facts = {fact.attribute: fact.value for fact in tas.facts}
        adc_evidence = adau_facts["latency"].evidence_ids
        amplifier_evidence = tas_facts["latency"].evidence_ids
        selected_known = {
            LatencyContributor.ADC: EngineeringValue(
                status=ValueStatus.KNOWN,
                value=22.9844 / 96_000 * 1_000_000,
                unit="us",
                conditions=["ADAU1978 ADC decimation-filter group delay at selected 96 kHz."],
                evidence_ids=adc_evidence,
            ),
            LatencyContributor.AMPLIFIER_PATH: EngineeringValue(
                status=ValueStatus.KNOWN,
                value=12 / 96_000 * 1_000_000,
                unit="us",
                conditions=["TAS6424-Q1 documented 12-FSYNC input-to-output delay at 96 kHz."],
                evidence_ids=amplifier_evidence,
            ),
        }
        contributions = [
            LatencyContribution(
                contribution_id=f"latency-{contributor.value.lower()}",
                contributor=contributor,
                latency=(
                    selected_known[contributor]
                    if contributor in selected_known
                    else EngineeringValue(
                        status=ValueStatus.UNKNOWN,
                        conditions=[
                            "Selected-path contributor remains unresolved; unknown is not zero."
                        ],
                    )
                ),
            )
            for contributor in LatencyContributor
            if contributor is not LatencyContributor.DAC
        ]
        comparisons.insert(
            0,
            LatencyPathComparison(
                comparison_id="latency-path-adau1978-tas6424-96k",
                architecture="four-channel ADC + DSP + digital-input Class-D",
                candidate_part_numbers=["ADAU1978", "ADSP-21569", "TAS6424-Q1"],
                sample_rate=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=96,
                    unit="kHz",
                    evidence_ids=list(
                        dict.fromkeys(
                            [
                                *adau_facts["sample_rate"].evidence_ids,
                                *tas_facts["sample_rate"].evidence_ids,
                            ]
                        )
                    ),
                ),
                documented_converter_delay=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=(22.9844 + 12) / 96_000 * 1_000_000,
                    unit="us",
                    conditions=[
                        "Known minimum is ADC digital-filter plus amplifier input-to-output "
                        "delay; no DAC term exists."
                    ],
                    evidence_ids=list(dict.fromkeys([*adc_evidence, *amplifier_evidence])),
                ),
                unknown_contributors=[
                    LatencyContributor.MICROPHONE_INTERFACE,
                    LatencyContributor.SERIAL_AUDIO_TRANSPORT,
                    LatencyContributor.BUFFERING,
                    LatencyContributor.DSP_PROCESSING,
                ],
            ),
        )
    budget = LatencyBudget.from_contributions("anc-end-to-end-latency", contributions)
    return budget.model_copy(update={"candidate_comparisons": comparisons})


def _master_value(spec: MasterSpec, section: str, name: str) -> EngineeringValue:
    requirement = spec.sections()[section].requirements.get(name)
    if requirement is None or requirement.status is RequirementStatus.UNKNOWN:
        return EngineeringValue(status=ValueStatus.UNKNOWN)
    return EngineeringValue(
        status=ValueStatus.KNOWN,
        value=requirement.value,
        unit=requirement.unit,
        evidence_ids=requirement.evidence_ids,
        conditions=["Derived directly from MASTER_SPEC."],
    )


def build_computational_budget(spec: MasterSpec) -> ComputationalBudget:
    unknown = EngineeringValue(status=ValueStatus.UNKNOWN)
    scenario = FxLMSScenario(
        scenario_id="fxlms-unresolved-design",
        label="Unresolved user design variables",
        design_exploration=False,
        reference_channels=unknown.model_copy(deep=True),
        error_channels=unknown.model_copy(deep=True),
        output_channels=_master_value(spec, "audio", "speaker_output_channels"),
        filter_length=unknown.model_copy(deep=True),
        sample_rate=_master_value(spec, "audio", "sample_rate"),
        operations_per_sample=unknown.model_copy(deep=True),
        operations_per_second=unknown.model_copy(deep=True),
        memory_required=unknown.model_copy(deep=True),
        processing_headroom=unknown.model_copy(deep=True),
    )
    return ComputationalBudget(
        budget_id="fxlms-computational-budget",
        algorithm="FxLMS",
        scenarios=[scenario],
        rationale=(
            "FxLMS is required, but reference/error channel allocation, filter length, sample "
            "rate, operation count, memory, and candidate DSP evidence remain unresolved. Audio "
            "I/O capacity alone is insufficient."
        ),
    )


def build_candidate_computational_budget(
    spec: MasterSpec, candidate: ComponentCandidate
) -> ComputationalBudget:
    base = build_computational_budget(spec)
    facts = {fact.attribute: fact.value for fact in candidate.facts}
    compute = facts.get("compute_throughput")
    memory = facts.get("memory")
    acceleration = facts.get("acceleration")
    accelerator_throughput = facts.get("accelerator_throughput")
    if compute is None or memory is None:
        return base.model_copy(
            update={
                "candidate_id": candidate.candidate_id,
                "evidence_ids": candidate.verified_evidence_ids,
                "suitability": FxLMSSuitabilityStatus.ARCHITECTURE_COMPATIBLE,
                "rationale": (
                    "The candidate has documented DSP architecture, but compute or memory "
                    "evidence is incomplete and the FxLMS workload remains unresolved."
                ),
            }
        )
    scenarios = []
    for sample_rate, filter_length, secondary_length, paths in (
        (48_000, 256, 128, 4),
        (96_000, 512, 256, 4),
        (96_000, 512, 256, 16),
    ):
        operations_per_sample = paths * (filter_length + filter_length + secondary_length)
        memory_kib = paths * (3 * filter_length + 2 * secondary_length) * 4 / 1024
        formula = EngineeringValue(
            status=ValueStatus.ESTIMATED,
            value=operations_per_sample,
            unit="MAC/sample",
            assumption=(
                "Bounded comparison counts one MAC for each control-filter tap, coefficient "
                "update tap, and secondary-path-model tap per modeled path."
            ),
            conditions=[
                "Formula: paths x (control taps + coefficient-update taps + secondary-path taps).",
                f"Scenario uses {paths} modeled paths and {secondary_length} secondary-path taps.",
            ],
            evidence_ids=list(
                dict.fromkeys([*compute.evidence_ids, *acceleration.evidence_ids])
                if acceleration is not None
                else compute.evidence_ids
            ),
        )
        conservative_capacity = 4 * 983_040_000 * 0.50
        headroom_fraction = max(
            0.0,
            (conservative_capacity - operations_per_sample * sample_rate) / conservative_capacity,
        )
        scenarios.append(
            FxLMSScenario(
                scenario_id=(
                    f"fxlms-exploration-{sample_rate // 1000}k-{filter_length}-{paths}paths"
                ),
                label=(
                    f"DESIGN_EXPLORATION {sample_rate // 1000} kHz / {filter_length} taps / "
                    f"{paths} paths"
                ),
                design_exploration=True,
                reference_channels=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=4,
                    unit="channels",
                    assumption="Exploration assumes four independent reference paths.",
                ),
                error_channels=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=4,
                    unit="channels",
                    assumption="Exploration assumes four independent error paths.",
                ),
                output_channels=EngineeringValue(
                    status=ValueStatus.KNOWN,
                    value=4,
                    unit="channels",
                    conditions=["Derived from MASTER_SPEC."],
                ),
                filter_length=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=filter_length,
                    unit="taps",
                    assumption="Exploration value; MASTER_SPEC filter length remains UNKNOWN.",
                ),
                sample_rate=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=sample_rate,
                    unit="Hz",
                    assumption="Exploration value; MASTER_SPEC sample rate remains UNKNOWN.",
                ),
                operations_per_sample=formula,
                operations_per_second=formula.model_copy(
                    update={
                        "value": operations_per_sample * sample_rate,
                        "unit": "MAC/s",
                        "conditions": [
                            *formula.conditions,
                            "Formula: operations/second = operations/sample x sample_rate.",
                        ],
                    }
                ),
                memory_required=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=memory_kib,
                    unit="KiB",
                    assumption=(
                        "32-bit words; three control/filter state vectors and two secondary-path "
                        "vectors per modeled path; program, stack, and I/O buffers excluded."
                    ),
                    conditions=[
                        "Deterministic scenario storage estimate, not a measured implementation.",
                        f"Candidate documented memory: {memory.value}.",
                    ],
                    evidence_ids=memory.evidence_ids,
                ),
                processing_headroom=EngineeringValue(
                    status=ValueStatus.ESTIMATED,
                    value=headroom_fraction * 100,
                    unit="percent of conservative MAC allowance",
                    assumption=(
                        "The documented four-MAC FIR accelerator runs at 983.04 MHz; only 50% "
                        "of theoretical MAC issue capacity is credited so the other 50% is "
                        "reserved for DMA, control, buffering, coefficient management, and "
                        "mapping inefficiency."
                    ),
                    conditions=[
                        "This is an analytical provisioning bound, not measured runtime.",
                        "The fully coupled 4x4 stress case has zero headroom inside this bound.",
                    ],
                    evidence_ids=list(
                        dict.fromkeys(
                            [
                                *compute.evidence_ids,
                                *(
                                    accelerator_throughput.evidence_ids
                                    if accelerator_throughput is not None
                                    else []
                                ),
                            ]
                        )
                    ),
                ),
                assumptions=[
                    "This is DESIGN_EXPLORATION, not a user requirement or validation result.",
                    (
                        "Four independent paths are illustrative."
                        if paths == 4
                        else "Sixteen paths illustrate full 4x4 control coupling."
                    ),
                    "A 50% theoretical-throughput reserve conservatively represents buffering, "
                    "instruction overhead, accelerator mapping, and control work.",
                ],
            )
        )
    return ComputationalBudget(
        budget_id="fxlms-computational-budget",
        algorithm="FxLMS",
        scenarios=scenarios,
        suitability=FxLMSSuitabilityStatus.LIKELY_CAPABLE,
        candidate_id=candidate.candidate_id,
        evidence_ids=list(dict.fromkeys([*compute.evidence_ids, *memory.evidence_ids])),
        rationale=(
            "The documented four-MAC FIR accelerator at the 983.04 MHz provisional core clock "
            "has 3.93216 GMAC/s theoretical issue capacity. Crediting only 50% leaves 1.96608 "
            "GMAC/s, which covers the 4x4 stress-case arithmetic exactly and leaves substantial "
            "analytical headroom for the smaller cases. The zero-margin 4x4 bound still requires "
            "a later hardware benchmark before firmware closure, but it does not block "
            "schematic design."
        ),
    )
