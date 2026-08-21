from __future__ import annotations

from ai_pcb.models.analysis import (
    ComputationalBudget,
    FxLMSScenario,
    FxLMSSuitabilityStatus,
    LatencyBudget,
    LatencyContribution,
    LatencyContributor,
)
from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.components import ComponentCandidate, ComponentCategory
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
    for contributor, attributes, categories in (
        (
            LatencyContributor.ADC,
            ("adc_latency", "latency"),
            {ComponentCategory.AUDIO_CODEC, ComponentCategory.ADC},
        ),
        (
            LatencyContributor.DAC,
            ("dac_latency", "latency"),
            {ComponentCategory.AUDIO_CODEC, ComponentCategory.DAC},
        ),
    ):
        candidate_terms: list[str] = []
        evidence_ids: list[str] = []
        for candidate in candidates:
            if candidate.category not in categories:
                continue
            fact = next(
                (fact for fact in candidate.facts if fact.attribute in attributes), None
            )
            if fact is None or fact.value.value is None:
                continue
            candidate_terms.append(
                f"{candidate.part_number}: {fact.value.value} {fact.value.unit or ''}".strip()
            )
            evidence_ids.extend(fact.value.evidence_ids)
        if not candidate_terms:
            continue
        replacement = LatencyContribution(
            contribution_id=f"latency-{contributor.value.lower()}",
            contributor=contributor,
            latency=EngineeringValue(
                status=ValueStatus.UNKNOWN,
                conditions=[
                    "Candidate-specific manufacturer group delay is available, but no converter "
                    "and sample-rate mode is selected; unknown is not zero.",
                    *candidate_terms,
                ],
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            ),
        )
        contributions = [
            replacement if item.contributor is contributor else item
            for item in contributions
        ]
    return LatencyBudget.from_contributions("anc-end-to-end-latency", contributions)


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
    for sample_rate, filter_length in ((48_000, 256), (96_000, 512)):
        unknown_formula = EngineeringValue(
            status=ValueStatus.UNKNOWN,
            conditions=[
                "Formula: operations/sample = Npaths x (control-filter work + "
                "coefficient-update work + secondary-path-filter work).",
                "The secondary-path filter length, MIMO coupling, buffering, and exact "
                "implementation are not requirements and remain UNKNOWN.",
            ],
            evidence_ids=list(
                dict.fromkeys([*compute.evidence_ids, *acceleration.evidence_ids])
                if acceleration is not None
                else compute.evidence_ids
            ),
        )
        scenarios.append(
            FxLMSScenario(
                scenario_id=f"fxlms-exploration-{sample_rate // 1000}k-{filter_length}",
                label=f"DESIGN_EXPLORATION {sample_rate // 1000} kHz / {filter_length} taps",
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
                operations_per_sample=unknown_formula.model_copy(deep=True),
                operations_per_second=unknown_formula.model_copy(
                    update={
                        "conditions": [
                            *unknown_formula.conditions,
                            "Formula: operations/second = operations/sample x sample_rate.",
                        ]
                    }
                ),
                memory_required=EngineeringValue(
                    status=ValueStatus.UNKNOWN,
                    conditions=[
                        "Formula depends on coefficient, state, secondary-path, buffering, "
                        "and numeric-format storage; those terms remain UNKNOWN.",
                        f"Candidate documented memory: {memory.value}.",
                    ],
                    evidence_ids=memory.evidence_ids,
                ),
                processing_headroom=EngineeringValue(
                    status=ValueStatus.UNKNOWN,
                    conditions=[
                        "Headroom requires a bounded operation count and measured implementation."
                    ],
                    evidence_ids=compute.evidence_ids,
                ),
                assumptions=[
                    "This is DESIGN_EXPLORATION, not a user requirement or validation result.",
                    "Four independent paths are illustrative; final MIMO topology is unresolved.",
                ],
            )
        )
    return ComputationalBudget(
        budget_id="fxlms-computational-budget",
        algorithm="FxLMS",
        scenarios=scenarios,
        suitability=FxLMSSuitabilityStatus.LIKELY_CAPABLE_PENDING_WORKLOAD,
        candidate_id=candidate.candidate_id,
        evidence_ids=list(
            dict.fromkeys([*compute.evidence_ids, *memory.evidence_ids])
        ),
        rationale=(
            "The documented core speed, on-chip memory, audio-oriented interfaces, and FIR/IIR "
            "acceleration make the candidate architecture-compatible and likely capable across "
            "useful design space. Final support is not verified because topology, sample rate, "
            "filter lengths, secondary-path model, operation count, and measured headroom remain "
            "unresolved."
        ),
    )
