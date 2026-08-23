from __future__ import annotations

from pydantic import JsonValue

from ai_pcb.models.analysis import ComputationalBudget, FxLMSSuitabilityStatus
from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.closure import (
    ClockSignal,
    DesignEnvelope,
    DesignEnvelopeScenario,
    DesignVariable,
    DesignVariableKind,
    DesignVariableStatus,
    MicrophoneFrontEnd,
    MicrophoneTechnologyOption,
    Phase4ReadinessAssessment,
    ProvisionalClockTree,
    ProvisionalPowerRail,
    ProvisionalPowerTree,
    ReadinessCriterion,
    ReadinessStatus,
)
from ai_pcb.models.components import ComponentCandidate
from ai_pcb.models.spec import MasterSpec, RequirementStatus
from ai_pcb.models.validation import ValidationStatus

_USER_CONSTRAINTS = {
    "electrical.speaker_impedance",
    "electrical.speaker_power_per_channel",
    "power.input_supply_voltage",
    "interfaces.control_interface",
    "interfaces.external_connectivity",
    "mechanical.pcb_dimensions",
    "environmental.operating_environment",
}


def _candidate(candidates: list[ComponentCandidate], part_number: str) -> ComponentCandidate | None:
    return next((item for item in candidates if item.part_number == part_number), None)


def _fact(candidate: ComponentCandidate | None, attribute: str) -> EngineeringValue | None:
    if candidate is None:
        return None
    fact = next((item.value for item in candidate.facts if item.attribute == attribute), None)
    return fact


def _resolved(
    variable_id: str,
    path: str | None,
    value: object,
    *,
    unit: str | None,
    evidence_ids: list[str],
    rationale: str,
) -> DesignVariable:
    return DesignVariable(
        variable_id=variable_id,
        master_spec_path=path,
        kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
        status=DesignVariableStatus.RESOLVED,
        rationale=rationale,
        resolution=EngineeringValue(
            status=ValueStatus.KNOWN,
            value=value,  # type: ignore[arg-type]
            unit=unit,
            evidence_ids=evidence_ids,
            conditions=["Engineering selection; this does not rewrite MASTER_SPEC."],
        ),
        evidence_ids=evidence_ids,
    )


def _known_engineering_value(
    value: JsonValue,
    unit: str,
    evidence_ids: list[str],
    conditions: list[str],
) -> EngineeringValue:
    return EngineeringValue(
        status=ValueStatus.KNOWN,
        value=value,
        unit=unit,
        evidence_ids=evidence_ids,
        conditions=conditions,
    )


def _estimated_engineering_value(
    value: JsonValue,
    unit: str,
    assumption: str,
    evidence_ids: list[str],
    conditions: list[str],
) -> EngineeringValue:
    return EngineeringValue(
        status=ValueStatus.ESTIMATED,
        value=value,
        unit=unit,
        assumption=assumption,
        evidence_ids=evidence_ids,
        conditions=conditions,
    )


def classify_and_close_design_variables(
    spec: MasterSpec, candidates: list[ComponentCandidate]
) -> list[DesignVariable]:
    """Classify every unresolved MASTER_SPEC value and close evidenced design choices."""

    variables: dict[str, DesignVariable] = {}
    for section_name, section in spec.sections().items():
        for name, requirement in section.requirements.items():
            if requirement.status is not RequirementStatus.UNKNOWN:
                continue
            path = f"{section_name}.{name}"
            kind = (
                DesignVariableKind.USER_CONSTRAINT
                if path in _USER_CONSTRAINTS
                else DesignVariableKind.ENGINEERING_DESIGN_VARIABLE
            )
            variables[path] = DesignVariable(
                variable_id=path,
                master_spec_path=path,
                kind=kind,
                status=(
                    DesignVariableStatus.USER_INPUT_REQUIRED
                    if kind is DesignVariableKind.USER_CONSTRAINT
                    else DesignVariableStatus.UNRESOLVED
                ),
                rationale=(
                    "This value describes the external system or user intent and cannot be "
                    "silently chosen by the engineering pipeline."
                    if kind is DesignVariableKind.USER_CONSTRAINT
                    else "This is an engineering choice, but current evidence is insufficient."
                ),
            )

    adsp = _candidate(candidates, "ADSP-21569")
    ad1938 = _candidate(candidates, "AD1938")
    tas = _candidate(candidates, "TAS6424-Q1")
    ad1938_rate = _fact(ad1938, "sample_rate")
    ad1938_depth = _fact(ad1938, "bit_depth")
    tas_rate = _fact(tas, "sample_rate")
    if ad1938_rate is not None and tas_rate is not None:
        evidence = list(dict.fromkeys([*ad1938_rate.evidence_ids, *tas_rate.evidence_ids]))
        variables["audio.sample_rate"] = _resolved(
            "audio.sample_rate",
            "audio.sample_rate",
            96,
            unit="kHz",
            evidence_ids=evidence,
            rationale=(
                "96 kHz is the highest evidenced common rate for the provisional AD1938 codec "
                "and TAS6424-Q1 output path and reduces their documented filter delays relative "
                "to 48 kHz."
            ),
        )
    if ad1938_depth is not None:
        variables["audio.bit_depth"] = _resolved(
            "audio.bit_depth",
            "audio.bit_depth",
            24,
            unit="bits",
            evidence_ids=ad1938_depth.evidence_ids,
            rationale="The provisional AD1938 conversion path is evidenced as 24-bit.",
        )
    if ad1938 is not None:
        codec_evidence = list(ad1938.verified_evidence_ids)
        for path in ("audio.adc_or_codec_model", "audio.dac_or_codec_model"):
            variables[path] = _resolved(
                path,
                path,
                "AD1938",
                unit=None,
                evidence_ids=codec_evidence,
                rationale=(
                    "AD1938 provisionally closes the synchronized four-input/eight-output "
                    "converter path and has lower documented 96 kHz converter filter delay than "
                    "PCM3168A."
                ),
            )
        variables["converter_architecture"] = _resolved(
            "converter_architecture",
            None,
            "multichannel codec + DSP",
            unit=None,
            evidence_ids=codec_evidence,
            rationale=(
                "One evidenced codec closes both converter directions; the separate-converter "
                "alternative still lacks an evidenced DAC."
            ),
        )
    if adsp is not None:
        variables["processing.dsp_model"] = _resolved(
            "processing.dsp_model",
            "processing.dsp_model",
            "ADSP-21569",
            unit=None,
            evidence_ids=list(adsp.verified_evidence_ids),
            rationale=(
                "Manufacturer evidence establishes the selected DSP architecture and resources."
            ),
        )
        debug = _fact(adsp, "programming_support")
        if debug is not None:
            variables["interfaces.programming_interface"] = _resolved(
                "interfaces.programming_interface",
                "interfaces.programming_interface",
                "IEEE 1149.1 JTAG",
                unit=None,
                evidence_ids=debug.evidence_ids,
                rationale="The provisional DSP documents an IEEE 1149.1 JTAG debug access port.",
            )
        clock = _fact(adsp, "clocking")
        codec_clock = _fact(ad1938, "clocking")
        if clock is not None and codec_clock is not None:
            clock_evidence = list(dict.fromkeys([*clock.evidence_ids, *codec_clock.evidence_ids]))
            variables["clock_architecture"] = DesignVariable(
                variable_id="clock_architecture",
                kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
                status=DesignVariableStatus.DESIGN_ENVELOPE,
                rationale=(
                    "A DSP-master synchronized clock direction is provisional; exact MCLK, "
                    "SPORT divider, jitter, and reset sequencing still require closure."
                ),
                envelope=DesignEnvelope(
                    envelope_id="audio-clock-envelope",
                    scenarios=[
                        DesignEnvelopeScenario(
                            scenario_id="dsp-master-codec-pll",
                            label="ADSP-21569 PCG master to AD1938 PLL",
                            value={
                                "master": "ADSP-21569 precision clock generator",
                                "codec_clocking": "AD1938 on-chip PLL",
                                "sample_rate_khz": 96,
                            },
                            conditions=[
                                "Exact MCLK multiple, dividers, jitter, and reset order are "
                                "UNKNOWN."
                            ],
                            evidence_ids=clock_evidence,
                        )
                    ],
                    assumptions=[
                        "This selects a clock direction for interface planning, not a verified "
                        "tree."
                    ],
                    selected_scenario_id="dsp-master-codec-pll",
                ),
                evidence_ids=clock_evidence,
            )

    load = _fact(tas, "speaker_load")
    power = _fact(tas, "output_power")
    voltage = _fact(tas, "input_voltage_range")
    if load is not None and power is not None:
        load_evidence = list(dict.fromkeys([*load.evidence_ids, *power.evidence_ids]))
        variables["electrical.speaker_impedance"] = DesignVariable(
            variable_id="electrical.speaker_impedance",
            master_spec_path="electrical.speaker_impedance",
            kind=DesignVariableKind.USER_CONSTRAINT,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "The actual speaker is still a user constraint; the amplifier may be designed "
                "provisionally for either documented load."
            ),
            envelope=DesignEnvelope(
                envelope_id="tas6424-speaker-load-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="speaker-load-2-ohm",
                        label="2 ohm speaker load",
                        value=2,
                        unit="ohm",
                        evidence_ids=load_evidence,
                    ),
                    DesignEnvelopeScenario(
                        scenario_id="speaker-load-4-ohm",
                        label="4 ohm speaker load",
                        value=4,
                        unit="ohm",
                        evidence_ids=load_evidence,
                    ),
                ],
                assumptions=[
                    "This envelope does not assert which speaker the user will connect.",
                    "Output power and thermal behavior remain conditional on PVDD, load, "
                    "and THD+N.",
                ],
                selected_scenario_id="speaker-load-4-ohm",
            ),
            evidence_ids=load_evidence,
        )
        variables["electrical.speaker_power_per_channel"] = DesignVariable(
            variable_id="electrical.speaker_power_per_channel",
            master_spec_path="electrical.speaker_power_per_channel",
            kind=DesignVariableKind.USER_CONSTRAINT,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "Conditional datasheet power points bound exploration without inventing a "
                "load target."
            ),
            envelope=DesignEnvelope(
                envelope_id="tas6424-power-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="power-14v4-4-ohm",
                        label="14.4 V / 4 ohm",
                        value=27,
                        unit="W/channel",
                        conditions=["14.4 V PVDD, 4 ohm, 10% THD+N."],
                        evidence_ids=power.evidence_ids,
                    ),
                    DesignEnvelopeScenario(
                        scenario_id="power-14v4-2-ohm",
                        label="14.4 V / 2 ohm",
                        value=45,
                        unit="W/channel",
                        conditions=["14.4 V PVDD, 2 ohm, 10% THD+N."],
                        evidence_ids=power.evidence_ids,
                    ),
                ],
                assumptions=["These are device conditions, not project output-power requirements."],
                selected_scenario_id="power-14v4-4-ohm",
            ),
            evidence_ids=power.evidence_ids,
        )
    if voltage is not None:
        variables["power.input_supply_voltage"] = DesignVariable(
            variable_id="power.input_supply_voltage",
            master_spec_path="power.input_supply_voltage",
            kind=DesignVariableKind.USER_CONSTRAINT,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "The external supply remains user-owned; TAS6424-Q1 bounds its PVDD rail only."
            ),
            envelope=DesignEnvelope(
                envelope_id="tas6424-pvdd-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="pvdd-recommended-range",
                        label="TAS6424-Q1 recommended PVDD range",
                        value={"minimum": 4.5, "maximum": 26.4},
                        unit="V",
                        conditions=list(voltage.conditions),
                        evidence_ids=voltage.evidence_ids,
                    )
                ],
                assumptions=["Other board rails and their current budgets are not yet closed."],
            ),
            evidence_ids=voltage.evidence_ids,
        )
        variables["power_tree"] = DesignVariable(
            variable_id="power_tree",
            kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "Only the amplifier PVDD branch is evidenced; converter, DSP, logic, sequencing, "
                "and current budgets remain open."
            ),
            envelope=DesignEnvelope(
                envelope_id="power-tree-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="pvdd-14v4",
                        label="14.4 V nominal amplifier branch",
                        value=14.4,
                        unit="V",
                        conditions=["Inside TAS6424-Q1 recommended PVDD range."],
                        evidence_ids=voltage.evidence_ids,
                    ),
                    DesignEnvelopeScenario(
                        scenario_id="pvdd-25v",
                        label="25 V high-power amplifier branch",
                        value=25,
                        unit="V",
                        conditions=["Inside TAS6424-Q1 recommended PVDD range."],
                        evidence_ids=voltage.evidence_ids,
                    ),
                ],
                assumptions=[
                    "Neither scenario defines the external supply or the remaining board rails."
                ],
            ),
            evidence_ids=voltage.evidence_ids,
        )

    variables["processing.filter_length"] = DesignVariable(
        variable_id="processing.filter_length",
        master_spec_path="processing.filter_length",
        kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
        status=DesignVariableStatus.DESIGN_ENVELOPE,
        rationale=(
            "Bounded FxLMS scenarios are retained pending plant identification and benchmarking."
        ),
        envelope=DesignEnvelope(
            envelope_id="fxlms-filter-envelope",
            scenarios=[
                DesignEnvelopeScenario(
                    scenario_id="fxlms-256-tap",
                    label="Independent-path baseline",
                    value=256,
                    unit="taps",
                ),
                DesignEnvelopeScenario(
                    scenario_id="fxlms-512-tap",
                    label="Long-filter or coupled-path stress case",
                    value=512,
                    unit="taps",
                ),
            ],
            assumptions=[
                "Filter lengths are design-exploration bounds, not user requirements.",
                "Final length requires acoustic plant data and measured convergence/performance.",
            ],
        ),
    )
    variables["fxlms_topology"] = DesignVariable(
        variable_id="fxlms_topology",
        kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
        status=DesignVariableStatus.DESIGN_ENVELOPE,
        rationale=(
            "Independent and fully coupled channel cases bound architectural compute analysis."
        ),
        envelope=DesignEnvelope(
            envelope_id="fxlms-topology-envelope",
            scenarios=[
                DesignEnvelopeScenario(
                    scenario_id="fxlms-4-independent",
                    label="Four independent control paths",
                    value={"paths": 4, "topology": "independent"},
                ),
                DesignEnvelopeScenario(
                    scenario_id="fxlms-4x4-coupled",
                    label="Fully coupled 4x4 control paths",
                    value={"paths": 16, "topology": "4x4 coupled"},
                ),
            ],
            assumptions=[
                "Acoustic coupling and secondary-path identification determine the final topology."
            ],
        ),
    )
    variables["mechanical.pcb_layer_count"] = DesignVariable(
        variable_id="mechanical.pcb_layer_count",
        master_spec_path="mechanical.pcb_layer_count",
        kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
        status=DesignVariableStatus.DESIGN_ENVELOPE,
        rationale="Mixed-signal partitioning is not yet detailed enough to choose a stackup.",
        envelope=DesignEnvelope(
            envelope_id="pcb-layer-envelope",
            scenarios=[
                DesignEnvelopeScenario(
                    scenario_id="pcb-4-layer", label="4-layer baseline", value=4
                ),
                DesignEnvelopeScenario(
                    scenario_id="pcb-6-layer", label="6-layer isolation option", value=6
                ),
            ],
            assumptions=[
                "These are exploration options only; stackup selection awaits power, placement, "
                "EMC, and mechanical closure."
            ],
        ),
    )
    adau = _candidate(candidates, "ADAU1978")
    adau_rate = _fact(adau, "sample_rate")
    adau_clock = _fact(adau, "clocking")
    adau_input = _fact(adau, "analog_input")
    tas_clock = _fact(tas, "clocking")
    if adau is not None and adau_rate is not None and tas_rate is not None:
        path_evidence = list(
            dict.fromkeys(
                [
                    *adau.verified_evidence_ids,
                    *(tas.verified_evidence_ids if tas is not None else []),
                    *(adsp.verified_evidence_ids if adsp is not None else []),
                ]
            )
        )
        variables["audio.sample_rate"] = _resolved(
            "audio.sample_rate",
            "audio.sample_rate",
            96,
            unit="kHz",
            evidence_ids=list(dict.fromkeys([*adau_rate.evidence_ids, *tas_rate.evidence_ids])),
            rationale=(
                "96 kHz is a documented common rate for ADAU1978 and TAS6424-Q1 and minimizes "
                "their documented digital-filter/sample latency among the amplifier's rates."
            ),
        )
        variables["audio.bit_depth"] = _resolved(
            "audio.bit_depth",
            "audio.bit_depth",
            24,
            unit="bits",
            evidence_ids=adau_rate.evidence_ids,
            rationale=(
                "ADAU1978 is documented for 24-bit conversion and TAS6424-Q1 accepts 24-bit TDM."
            ),
        )
        variables["audio.adc_or_codec_model"] = _resolved(
            "audio.adc_or_codec_model",
            "audio.adc_or_codec_model",
            "ADAU1978",
            unit=None,
            evidence_ids=list(adau.verified_evidence_ids),
            rationale=(
                "ADAU1978 closes four synchronized analog input channels without an unused DAC."
            ),
        )
        variables["audio.dac_or_codec_model"] = _resolved(
            "audio.dac_or_codec_model",
            "audio.dac_or_codec_model",
            "NOT_APPLICABLE: digital-input Class-D path",
            unit=None,
            evidence_ids=list(tas.verified_evidence_ids) if tas is not None else path_evidence,
            rationale="No DAC exists in the selected all-digital DSP-to-amplifier output path.",
        )
        variables["converter_architecture"] = _resolved(
            "converter_architecture",
            None,
            "4-channel ADC + DSP + digital-input Class-D",
            unit=None,
            evidence_ids=path_evidence,
            rationale=(
                "This is the lowest-complexity compatible path: ADAU1978 TDM output feeds the "
                "DSP and the DSP TDM output feeds TAS6424-Q1 directly."
            ),
        )
    if adau is not None and adau_input is not None:
        mic_evidence = list(dict.fromkeys([*adau_input.evidence_ids, *adau.verified_evidence_ids]))
        for variable_id, value, rationale in (
            (
                "audio.microphone_technology",
                "differential analog MEMS microphone design envelope",
                "Differential analog MEMS preserves a direct, synchronized four-channel ADC path.",
            ),
            (
                "audio.microphone_electrical_interface",
                "AC-coupled differential analog",
                "The selected ADC exposes four differential 2 V rms full-scale inputs.",
            ),
            (
                "audio.microphone_signal_level",
                "AFE output <= 2 V rms differential at 1.5 V common mode",
                "The exact microphone sensitivity is user/acoustic dependent; the ADC input "
                "envelope is exact.",
            ),
        ):
            variables[variable_id] = _resolved(
                variable_id,
                variable_id,
                value,
                unit=None,
                evidence_ids=mic_evidence,
                rationale=rationale,
            )
    if adsp is not None and adau_clock is not None and tas_clock is not None:
        clock_evidence = list(
            dict.fromkeys(
                [*adsp.verified_evidence_ids, *adau_clock.evidence_ids, *tas_clock.evidence_ids]
            )
        )
        variables["clock_architecture"] = _resolved(
            "clock_architecture",
            None,
            "24.576 MHz common source; DSP PCG master; 12.288 MHz BCLK; 96 kHz FSYNC",
            unit=None,
            evidence_ids=clock_evidence,
            rationale=(
                "Exact integer-related clocks keep ADC, DSP SPORTs, and amplifier synchronous."
            ),
        )
    adp = _candidate(candidates, "ADP5054")
    if adp is not None:
        power_evidence = list(
            dict.fromkeys(
                [
                    *adp.verified_evidence_ids,
                    *(tas.verified_evidence_ids if tas is not None else []),
                ]
            )
        )
        variables["power.input_supply_voltage"] = DesignVariable(
            variable_id="power.input_supply_voltage",
            master_spec_path="power.input_supply_voltage",
            kind=DesignVariableKind.USER_CONSTRAINT,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "The common documented regulated-input range is retained as an envelope; "
                "14.4 V is the provisional nominal amplifier operating point."
            ),
            envelope=DesignEnvelope(
                envelope_id="phase33-regulated-input-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="regulated-4v5-15v5",
                        label="Common regulated input range",
                        value={"minimum": 4.5, "nominal": 14.4, "maximum": 15.5},
                        unit="V",
                        conditions=["Inside both ADP5054 VIN and TAS6424-Q1 PVDD/VBAT ranges."],
                        evidence_ids=power_evidence,
                    )
                ],
                assumptions=[
                    "This is a design envelope, not a silent update to the user requirement."
                ],
                selected_scenario_id="regulated-4v5-15v5",
            ),
            evidence_ids=power_evidence,
        )
        variables["power_tree"] = _resolved(
            "power_tree",
            None,
            "4.5-15.5 V regulated input; direct amplifier PVDD/VBAT; ADP5054 3.3/1.8/1.0 V rails",
            unit=None,
            evidence_ids=power_evidence,
            rationale=(
                "ADP5054 covers the provisional regulated input and required low-voltage rails; "
                "the amplifier remains on the protected high-current input branch."
            ),
        )
        variables["power.power_budget"] = DesignVariable(
            variable_id="power.power_budget",
            master_spec_path="power.power_budget",
            kind=DesignVariableKind.ENGINEERING_DESIGN_VARIABLE,
            status=DesignVariableStatus.DESIGN_ENVELOPE,
            rationale=(
                "Known device conditions bound the supply while output load remains user-owned."
            ),
            envelope=DesignEnvelope(
                envelope_id="phase33-power-budget-envelope",
                scenarios=[
                    DesignEnvelopeScenario(
                        scenario_id="digital-only-known-minimum",
                        label="Known documented active contributions",
                        value=1.267,
                        unit="W",
                        conditions=["DSP core plus ADAU1978 and TAS6424-Q1 logic only."],
                        evidence_ids=power_evidence,
                    ),
                    DesignEnvelopeScenario(
                        scenario_id="amplifier-25w-four-channel",
                        label="Documented amplifier stress point",
                        value=116.3,
                        unit="W input to amplifier",
                        conditions=["Four channels at 25 W and documented 86% efficiency."],
                        evidence_ids=list(tas.verified_evidence_ids) if tas is not None else [],
                    ),
                ],
                assumptions=[
                    "DSP I/O, control, microphone, regulator loss, and exact speaker demand "
                    "remain explicit unknowns."
                ],
            ),
            evidence_ids=power_evidence,
        )
    return list(variables.values())


def build_microphone_front_end(candidates: list[ComponentCandidate]) -> MicrophoneFrontEnd:
    adau = _candidate(candidates, "ADAU1978")
    analog = _fact(adau, "analog_input")
    if adau is None or analog is None:
        raise ValueError("ADAU1978 analog-input evidence is required for microphone closure")
    return MicrophoneFrontEnd(
        architecture_id="four-channel-differential-analog-mems",
        channel_count=4,
        selected_technology="differential analog MEMS microphone design envelope",
        selected_interface="AC-coupled differential analog",
        adc_part_number="ADAU1978",
        adc_topology="four simultaneous ADC channels to one TDM4 stream",
        analog_front_end_requirements=[
            "Per-channel low-noise differential gain is required unless the microphone can "
            "directly use the ADC range.",
            "AFE output must remain within 2 V rms differential full scale and 1.5 V input "
            "common mode.",
            "Gain, coupling, high-pass corner, bias, input noise, and anti-RF values remain "
            "calculated from the selected microphone datasheet.",
            "All four channels require matched topology and tolerances; digital gain is not "
            "a substitute for analog noise performance.",
        ],
        options=[
            MicrophoneTechnologyOption(
                option_id="differential-analog-mems",
                technology="differential analog MEMS",
                interface="differential voltage",
                selected=True,
                rationale=(
                    "Directly matches the evidenced ADC topology with no PDM decimation or "
                    "extra digital clock domain."
                ),
                evidence_ids=analog.evidence_ids,
            ),
            MicrophoneTechnologyOption(
                option_id="pdm-mems",
                technology="PDM MEMS",
                interface="PDM clock/data",
                rationale=(
                    "Rejected because a four-channel PDM capture/decimation path is not "
                    "evidenced for the selected DSP."
                ),
            ),
            MicrophoneTechnologyOption(
                option_id="analog-electret",
                technology="electret condenser",
                interface="biased single-ended analog plus differential AFE",
                rationale=(
                    "Retained only if acoustic/environment requirements justify its extra "
                    "bias and AFE complexity."
                ),
            ),
        ],
        unresolved_terms=[
            "Exact microphone part, sensitivity, acoustic overload point, and placement "
            "depend on the acoustic plant.",
            "Exact AFE gain and passive values remain UNKNOWN until a microphone part is chosen.",
        ],
        evidence_ids=list(adau.verified_evidence_ids),
    )


def build_clock_tree(candidates: list[ComponentCandidate]) -> ProvisionalClockTree:
    adsp = _candidate(candidates, "ADSP-21569")
    adau = _candidate(candidates, "ADAU1978")
    tas = _candidate(candidates, "TAS6424-Q1")
    if adsp is None or adau is None or tas is None:
        raise ValueError("DSP, ADC, and amplifier evidence are required for clock closure")
    evidence = list(
        dict.fromkeys(
            [*adsp.verified_evidence_ids, *adau.verified_evidence_ids, *tas.verified_evidence_ids]
        )
    )
    return ProvisionalClockTree(
        tree_id="phase33-common-24576-clock-tree",
        source_frequency_hz=24_576_000,
        sample_rate_hz=96_000,
        audio_master="ADSP-21569 PCG/SPORT",
        signals=[
            ClockSignal(
                signal_id="audio-mclk",
                source="24.576 MHz low-jitter 3.3 V oscillator",
                sinks=[
                    "ADAU1978 MCLKIN",
                    "TAS6424-Q1 MCLK",
                    "ADSP-21569 SYS_CLKIN0 through 3.3-to-1.8 V clock translation",
                ],
                frequency_hz=24_576_000,
                relationship="256 x fS",
                divider="source / 1",
                jitter_sensitive=True,
                evidence_ids=evidence,
            ),
            ClockSignal(
                signal_id="audio-bclk",
                source="ADSP-21569 PCG",
                sinks=["ADAU1978 BCLK", "DSP input/output SPORTs", "TAS6424-Q1 SCLK"],
                frequency_hz=12_288_000,
                relationship="128 x fS for four 32-bit TDM slots",
                divider="PCG CLKDIV = 2 from 24.576 MHz",
                jitter_sensitive=True,
                evidence_ids=evidence,
            ),
            ClockSignal(
                signal_id="audio-fsync",
                source="ADSP-21569 PCG",
                sinks=["ADAU1978 LRCLK", "DSP input/output SPORTs", "TAS6424-Q1 FSYNC"],
                frequency_hz=96_000,
                relationship="fS, one pulse per 128-bit TDM frame",
                divider="PCG FSDIV = 256 from 24.576 MHz",
                jitter_sensitive=True,
                evidence_ids=evidence,
            ),
            ClockSignal(
                signal_id="dsp-core-clock",
                source="ADSP-21569 CGU PLL",
                sinks=["SHARC+ core", "SYSCLK", "SCLK0"],
                frequency_hz=983_040_000,
                relationship="PLLCLK 1.96608 GHz, CCLK /2, SYSCLK /4, SCLK0 /4 from SYSCLK",
                divider="DF=0, MSEL=80, CSEL=2, SYSSEL=4, S0SEL=4",
                evidence_ids=evidence,
            ),
        ],
        synchronization_strategy=(
            "One oscillator is the root for converter MCLK, DSP CGU, and PCG-derived TDM "
            "clocks; no ASRC is used."
        ),
        jitter_strategy=[
            "Route oscillator directly to ADC and amplifier MCLK before any DSP level translation.",
            "Use a low-additive-jitter 3.3-to-1.8 V translator only on SYS_CLKIN0 and "
            "verify timing during schematic review.",
            "Keep MCLK/BCLK/FSYNC away from Class-D switching nodes and regulator switch nodes.",
        ],
        reset_strategy=[
            "Hold DSP SYS_HWRST until all rails and SYS_CLKIN0 are stable.",
            "Hold ADAU1978 PD/RST low until 3.3 V and MCLK are stable, then wait at least "
            "the documented 10 ms PLL lock before PWUP.",
            "Keep TAS6424-Q1 muted/standby until valid MCLK, SCLK, FSYNC, and I2C "
            "configuration are present.",
        ],
        evidence_ids=evidence,
    )


def build_power_tree(candidates: list[ComponentCandidate]) -> ProvisionalPowerTree:
    adsp = _candidate(candidates, "ADSP-21569")
    adau = _candidate(candidates, "ADAU1978")
    tas = _candidate(candidates, "TAS6424-Q1")
    adp = _candidate(candidates, "ADP5054")
    if any(candidate is None for candidate in (adsp, adau, tas, adp)):
        raise ValueError("DSP, ADC, amplifier, and PMIC evidence are required for power closure")
    assert adsp is not None and adau is not None and tas is not None and adp is not None
    evidence = list(
        dict.fromkeys(
            [
                *adsp.verified_evidence_ids,
                *adau.verified_evidence_ids,
                *tas.verified_evidence_ids,
                *adp.verified_evidence_ids,
            ]
        )
    )
    return ProvisionalPowerTree(
        tree_id="phase33-regulated-4v5-15v5-power-tree",
        input_envelope=DesignEnvelope(
            envelope_id="regulated-input-envelope",
            scenarios=[
                DesignEnvelopeScenario(
                    scenario_id="regulated-4v5-15v5",
                    label="Regulated external DC input",
                    value={"minimum": 4.5, "nominal": 14.4, "maximum": 15.5},
                    unit="V",
                    conditions=[
                        "Must remain inside ADP5054 input and TAS6424-Q1 PVDD/VBAT ranges."
                    ],
                    evidence_ids=evidence,
                )
            ],
            assumptions=[
                "Raw automotive battery/transient operation is outside this provisional envelope."
            ],
            selected_scenario_id="regulated-4v5-15v5",
        ),
        rails=[
            ProvisionalPowerRail(
                rail_id="pvdd-vbat",
                nominal_voltage=_known_engineering_value(
                    14.4,
                    "V",
                    tas.verified_evidence_ids,
                    ["Direct protected input branch; 4.5-15.5 V envelope."],
                ),
                source="protected external input",
                consumers=["TAS6424-Q1 PVDD", "TAS6424-Q1 VBAT"],
                regulator_class="unregulated protected high-current branch",
                current_budget=_estimated_engineering_value(
                    10,
                    "A",
                    "Connector/fuse allowance above the documented 8.1 A four-channel 25 W "
                    "operating point.",
                    tas.verified_evidence_ids,
                    ["Actual speaker demand remains UNKNOWN."],
                ),
                sequence=(
                    "Available at input; amplifier held in standby/mute until logic and "
                    "clocks are valid."
                ),
                evidence_ids=tas.verified_evidence_ids,
            ),
            ProvisionalPowerRail(
                rail_id="3v3-digital-analog",
                nominal_voltage=_known_engineering_value(
                    3.3, "V", evidence, ["ADSP VDD_EXT, ADAU AVDD/IOVDD, TAS VDD."]
                ),
                source="ADP5054 channel 3",
                consumers=[
                    "ADSP-21569 VDD_EXT",
                    "ADAU1978 AVDD/IOVDD",
                    "TAS6424-Q1 VDD",
                    "clock/control logic",
                    "microphone/AFE post-filter branch",
                ],
                regulator_class=(
                    "2.5 A synchronous buck plus low-noise filtering for ADC/microphone branch"
                ),
                provisional_regulator="ADP5054",
                current_budget=_known_engineering_value(
                    2.5,
                    "A provisioned",
                    adp.verified_evidence_ids,
                    [
                        "Known ADAU1978 and TAS logic current is small; DSP I/O and AFE "
                        "remain UNKNOWN."
                    ],
                ),
                noise_sensitive=True,
                sequence=(
                    "Enable with 1.8 V so DSP VDD_EXT delta constraints remain satisfied; "
                    "filter analog consumers locally."
                ),
                evidence_ids=evidence,
            ),
            ProvisionalPowerRail(
                rail_id="1v8-reference-analog",
                nominal_voltage=_known_engineering_value(
                    1.8,
                    "V",
                    adsp.verified_evidence_ids,
                    ["ADSP VDD_REF and VDD_ANA; ADAU DVDD is internally generated."],
                ),
                source="ADP5054 channel 4",
                consumers=[
                    "ADSP-21569 VDD_REF",
                    "ADSP-21569 VDD_ANA",
                    "clock translator low-voltage side",
                ],
                regulator_class="2.5 A synchronous buck with local low-noise filtering",
                provisional_regulator="ADP5054",
                current_budget=_known_engineering_value(
                    2.5,
                    "A provisioned",
                    adp.verified_evidence_ids,
                    ["Actual domain current remains UNKNOWN pending pin-level schematic budget."],
                ),
                noise_sensitive=True,
                sequence=(
                    "Ramp with 3.3 V and enforce the documented VDD_EXT delta limit at all times."
                ),
                evidence_ids=evidence,
            ),
            ProvisionalPowerRail(
                rail_id="1v0-dsp-core",
                nominal_voltage=_known_engineering_value(
                    1.0, "V", adsp.verified_evidence_ids, ["ADSP-21569 VDD_INT."]
                ),
                source="ADP5054 channel 1",
                consumers=["ADSP-21569 VDD_INT"],
                regulator_class="high-current synchronous buck",
                provisional_regulator="ADP5054",
                current_budget=_estimated_engineering_value(
                    1.5,
                    "A",
                    "30% provisioning margin over the documented 1.157 A typical "
                    "full-activity condition.",
                    adsp.verified_evidence_ids,
                    ["Final value must use EE-414 with firmware activity factors."],
                ),
                sequence=(
                    "May ramp with other DSP rails; SYS_HWRST remains asserted until all "
                    "rails and clock are stable."
                ),
                evidence_ids=evidence,
            ),
        ],
        known_minimum_power=_known_engineering_value(
            1.267,
            "W",
            evidence,
            [
                "DSP core typical plus ADAU1978 and TAS6424-Q1 logic documented active "
                "terms; excludes all unknowns and amplifier output."
            ],
        ),
        estimated_design_power=_estimated_engineering_value(
            120,
            "W",
            "Rounded board input envelope for the documented four-channel 25 W amplifier "
            "stress point plus digital loads.",
            evidence,
            ["This is a design envelope, not a user power requirement."],
        ),
        unknown_contributors=[
            "ADSP-21569 VDD_EXT/VDD_REF/VDD_ANA current",
            "microphone and AFE current",
            "control, flash, clock translation, and indicator current",
            "ADP5054 conversion losses at final operating points",
            "actual loudspeaker power profile",
        ],
        sequencing_strategy=[
            "Use ADP5054 individual enable/soft-start controls for the 3.3 V, 1.8 V, and "
            "1.0 V rails.",
            "Supervise all DSP rails and 24.576 MHz clock before releasing SYS_HWRST.",
            "Release ADAU1978 after its rail/clock delay; release amplifier mute last; "
            "reverse the order on shutdown.",
        ],
        thermal_implications=[
            "The documented 86% efficiency at four channels x 25 W implies about 16.3 W "
            "amplifier-stage loss and requires exposed-pad copper/thermal validation.",
            "ADSP core is approximately 1.16 W at the documented 1 GHz full-activity "
            "condition before other domains.",
            "ADP5054 loss is condition-dependent and must be calculated after inductor, "
            "frequency, and load selection.",
        ],
        evidence_ids=evidence,
    )


def assess_phase4_readiness(
    variables: list[DesignVariable],
    candidates: list[ComponentCandidate],
    microphone_front_end: MicrophoneFrontEnd | None = None,
    clock_tree: ProvisionalClockTree | None = None,
    power_tree: ProvisionalPowerTree | None = None,
    computational_budget: ComputationalBudget | None = None,
) -> Phase4ReadinessAssessment:
    by_id = {item.variable_id: item for item in variables}
    adsp = _candidate(candidates, "ADSP-21569")
    adau = _candidate(candidates, "ADAU1978")
    tas = _candidate(candidates, "TAS6424-Q1")
    adp = _candidate(candidates, "ADP5054")
    evidence = list(
        dict.fromkeys(
            evidence_id
            for candidate in (adsp, adau, tas, adp)
            if candidate is not None
            for evidence_id in candidate.verified_evidence_ids
        )
    )
    criteria = [
        ReadinessCriterion(
            criterion_id="major-architecture",
            description="Major architecture is selected or provisionally selected",
            status=ValidationStatus.PASS,
            rationale=(
                "Four-channel ADC + DSP + digital-input Class-D is provisionally selected; "
                "the codec-DAC path is rejected as incompatible with this amplifier."
            ),
            evidence_ids=evidence,
        ),
        ReadinessCriterion(
            criterion_id="dsp-path",
            description="DSP path is sufficiently justified",
            status=(
                ValidationStatus.PASS
                if adsp is not None
                and computational_budget is not None
                and computational_budget.suitability
                in {
                    FxLMSSuitabilityStatus.LIKELY_CAPABLE,
                    FxLMSSuitabilityStatus.ANALYTICALLY_SUPPORTED,
                    FxLMSSuitabilityStatus.REQUIRES_HARDWARE_BENCHMARK,
                }
                else ValidationStatus.UNKNOWN
            ),
            rationale=(
                "ADSP-21569 is architecture-compatible and has explicit bounded FxLMS scenarios."
            ),
            evidence_ids=list(adsp.verified_evidence_ids) if adsp is not None else [],
        ),
        ReadinessCriterion(
            criterion_id="converter-path",
            description="Converter architecture is sufficiently justified",
            status=ValidationStatus.PASS if adau is not None else ValidationStatus.UNKNOWN,
            rationale=(
                "ADAU1978 closes four synchronized ADC channels; no DAC is present in the "
                "selected digital-input amplifier path."
            ),
            evidence_ids=list(adau.verified_evidence_ids) if adau is not None else [],
        ),
        ReadinessCriterion(
            criterion_id="class-d-envelope",
            description="Class-D selection or safe design envelope exists",
            status=(
                ValidationStatus.PASS
                if tas is not None
                and by_id.get("electrical.speaker_impedance") is not None
                and by_id["electrical.speaker_impedance"].envelope is not None
                else ValidationStatus.UNKNOWN
            ),
            rationale=(
                "TAS6424-Q1 is provisional only inside its evidenced load, supply, and "
                "power envelope."
            ),
            evidence_ids=list(tas.verified_evidence_ids) if tas is not None else [],
        ),
        ReadinessCriterion(
            criterion_id="major-interface-compatibility",
            description="Major interface compatibility is understood",
            status=(
                ValidationStatus.PASS
                if microphone_front_end is not None and clock_tree is not None
                else ValidationStatus.UNKNOWN
            ),
            rationale=(
                "Differential analog microphones feed ADAU1978; synchronized TDM4 connects "
                "ADC, DSP, and TAS6424-Q1 without an analog/digital mismatch."
            ),
            evidence_ids=evidence,
        ),
        ReadinessCriterion(
            criterion_id="clock-tree",
            description="Clock tree and synchronization are provisionally defined",
            status=ValidationStatus.PASS if clock_tree is not None else ValidationStatus.UNKNOWN,
            rationale=(
                "A common 24.576 MHz root and exact integer dividers define converter, DSP, "
                "and TDM clocks."
            ),
            evidence_ids=clock_tree.evidence_ids if clock_tree is not None else [],
        ),
        ReadinessCriterion(
            criterion_id="power-tree",
            description="Whole-board provisional power tree exists",
            status=ValidationStatus.PASS if power_tree is not None else ValidationStatus.UNKNOWN,
            rationale=(
                "Input envelope, rails, regulator classes, sequencing, current bounds, and "
                "thermal risks are explicit."
            ),
            evidence_ids=power_tree.evidence_ids if power_tree is not None else [],
        ),
        ReadinessCriterion(
            criterion_id="remaining-unknowns",
            description="Remaining unknowns are safe to close during schematic verification",
            status=ValidationStatus.WARNING,
            rationale=(
                "Exact microphone/AFE values, speaker demand, rail losses, and firmware timing "
                "remain explicit and are bounded by schematic-stage envelopes."
            ),
        ),
        ReadinessCriterion(
            criterion_id="known-hard-constraints",
            description="No known hard constraint is violated",
            status=ValidationStatus.PASS,
            rationale=(
                "No evidenced candidate or selected architecture violates a known hard requirement."
            ),
            evidence_ids=evidence,
        ),
    ]
    blocked = any(
        criterion.status in {ValidationStatus.FAIL, ValidationStatus.UNKNOWN}
        for criterion in criteria
    )
    blockers = (
        [
            criterion.rationale
            for criterion in criteria
            if criterion.status is ValidationStatus.UNKNOWN
        ]
        if blocked
        else []
    )
    return Phase4ReadinessAssessment(
        status=(
            ReadinessStatus.NOT_READY_FOR_PHASE_4 if blocked else ReadinessStatus.READY_FOR_PHASE_4
        ),
        criteria=criteria,
        blockers=blockers,
    )
