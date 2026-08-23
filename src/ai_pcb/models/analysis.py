from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel


class LatencyContributor(StrEnum):
    MICROPHONE_INTERFACE = "MICROPHONE_INTERFACE"
    ADC = "ADC"
    SERIAL_AUDIO_TRANSPORT = "SERIAL_AUDIO_TRANSPORT"
    BUFFERING = "BUFFERING"
    DSP_PROCESSING = "DSP_PROCESSING"
    DAC = "DAC"
    AMPLIFIER_PATH = "AMPLIFIER_PATH"


class LatencyContribution(StrictModel):
    contribution_id: Identifier
    contributor: LatencyContributor
    latency: EngineeringValue
    latency_critical: bool = True

    @model_validator(mode="after")
    def latency_has_unit_when_numeric(self) -> LatencyContribution:
        if self.latency.status is not ValueStatus.UNKNOWN and not self.latency.unit:
            raise ValueError("known or estimated latency requires a unit")
        return self


class LatencyPathComparison(StrictModel):
    comparison_id: Identifier
    architecture: NonEmptyString
    candidate_part_numbers: list[NonEmptyString] = Field(min_length=1)
    sample_rate: EngineeringValue
    documented_converter_delay: EngineeringValue
    unknown_contributors: list[LatencyContributor] = Field(default_factory=list)


class LatencyBudget(StrictModel):
    budget_id: Identifier
    contributions: list[LatencyContribution] = Field(min_length=1)
    total: EngineeringValue
    candidate_comparisons: list[LatencyPathComparison] = Field(default_factory=list)

    @classmethod
    def from_contributions(
        cls, budget_id: str, contributions: list[LatencyContribution]
    ) -> LatencyBudget:
        if any(item.latency.status is ValueStatus.UNKNOWN for item in contributions):
            total = EngineeringValue(
                status=ValueStatus.UNKNOWN,
                conditions=["At least one latency contributor is unresolved."],
            )
        else:
            units = {item.latency.unit for item in contributions}
            raw_values = [item.latency.value for item in contributions]
            numeric_values = [
                float(value)
                for value in raw_values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if len(units) != 1 or len(numeric_values) != len(raw_values):
                total = EngineeringValue(
                    status=ValueStatus.UNKNOWN,
                    conditions=["Latency terms cannot be summed without compatible numeric units."],
                )
            else:
                total = EngineeringValue(
                    status=(
                        ValueStatus.ESTIMATED
                        if any(
                            item.latency.status is ValueStatus.ESTIMATED for item in contributions
                        )
                        else ValueStatus.KNOWN
                    ),
                    value=sum(numeric_values),
                    unit=next(iter(units)),
                    conditions=["Sum of the listed latency contributors."],
                    evidence_ids=list(
                        dict.fromkeys(
                            evidence_id
                            for item in contributions
                            for evidence_id in item.latency.evidence_ids
                        )
                    ),
                    assumption=(
                        "One or more contributor values are explicitly estimated."
                        if any(
                            item.latency.status is ValueStatus.ESTIMATED for item in contributions
                        )
                        else None
                    ),
                )
        return cls(budget_id=budget_id, contributions=contributions, total=total)


class FxLMSScenario(StrictModel):
    scenario_id: Identifier
    label: NonEmptyString
    design_exploration: bool
    reference_channels: EngineeringValue
    error_channels: EngineeringValue
    output_channels: EngineeringValue
    filter_length: EngineeringValue
    sample_rate: EngineeringValue
    operations_per_sample: EngineeringValue
    operations_per_second: EngineeringValue
    memory_required: EngineeringValue
    processing_headroom: EngineeringValue
    assumptions: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def exploratory_assumptions_are_labeled(self) -> FxLMSScenario:
        if self.design_exploration and not self.assumptions:
            raise ValueError("design-exploration scenarios require labeled assumptions")
        return self


class FxLMSSuitabilityStatus(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    LIKELY_CAPABLE = "LIKELY_CAPABLE"
    ANALYTICALLY_SUPPORTED = "ANALYTICALLY_SUPPORTED"
    REQUIRES_HARDWARE_BENCHMARK = "REQUIRES_HARDWARE_BENCHMARK"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    ARCHITECTURE_COMPATIBLE = "ARCHITECTURE_COMPATIBLE"
    LIKELY_CAPABLE_PENDING_WORKLOAD = "LIKELY_CAPABLE_PENDING_WORKLOAD"
    EVIDENCE_VERIFIED_FOR_SCENARIO = "EVIDENCE_VERIFIED_FOR_SCENARIO"
    UNKNOWN = "UNKNOWN"


class ComputationalBudget(StrictModel):
    budget_id: Identifier
    algorithm: NonEmptyString
    scenarios: list[FxLMSScenario] = Field(min_length=1)
    suitability: FxLMSSuitabilityStatus = FxLMSSuitabilityStatus.UNKNOWN
    candidate_id: Identifier | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)
    rationale: NonEmptyString

    @model_validator(mode="after")
    def support_requires_compute_evidence(self) -> ComputationalBudget:
        if self.suitability in {
            FxLMSSuitabilityStatus.SUPPORTED,
            FxLMSSuitabilityStatus.EVIDENCE_VERIFIED_FOR_SCENARIO,
            FxLMSSuitabilityStatus.ANALYTICALLY_SUPPORTED,
        }:
            if self.candidate_id is None or not self.evidence_ids:
                raise ValueError("supported FxLMS suitability requires a candidate and evidence")
            scenario_unknown = any(
                value.status is ValueStatus.UNKNOWN
                for scenario in self.scenarios
                for value in (
                    scenario.filter_length,
                    scenario.sample_rate,
                    scenario.operations_per_second,
                    scenario.memory_required,
                    scenario.processing_headroom,
                )
            )
            if scenario_unknown:
                raise ValueError("FxLMS cannot be supported while compute terms remain unknown")
        if self.suitability in {
            FxLMSSuitabilityStatus.ARCHITECTURE_COMPATIBLE,
            FxLMSSuitabilityStatus.LIKELY_CAPABLE_PENDING_WORKLOAD,
            FxLMSSuitabilityStatus.LIKELY_CAPABLE,
            FxLMSSuitabilityStatus.REQUIRES_HARDWARE_BENCHMARK,
        } and (self.candidate_id is None or not self.evidence_ids):
            raise ValueError("evidence-grounded FxLMS compatibility requires candidate evidence")
        return self
