from __future__ import annotations

from pathlib import Path

from ai_pcb.kicad import KiCadSchematicBackend
from ai_pcb.models.schematic import (
    EngineeringCalculation,
    InterfaceRole,
    InterfaceSignal,
    NetClass,
    PhysicalPin,
    PinElectricalType,
    PinReference,
    SchematicComponent,
    SchematicDesign,
    SchematicInterface,
    SchematicNet,
    SchematicRail,
    SchematicSheet,
    SchematicUnresolvedItem,
)
from ai_pcb.models.validation import ValidationStatus
from ai_pcb.schematic.calculations import (
    adp5054_feedback_top_ohms,
    adp5054_inductor_h,
    differential_high_pass_hz,
    tdm_bit_clock_hz,
)

PROJECT = Path(__file__).resolve().parent
OUTPUT = PROJECT / "outputs" / "kicad"

E_ADAU = "fact-adau1978-clocking"
E_DSP = "fact-adsp-21569-operating-rails"
E_DSP_PINS = "acquisition-29511604a3f976beb37bb6d3"
E_DSP_REF = "acquisition-c38de8a5afaf388b9d163fb6"
E_TAS = "fact-tas6424-clocking"
E_ADP = "fact-adp5054-output-voltage"
E_THP = "acquisition-0322671c82a293c0245e9875"
E_TRANSLATOR = "acquisition-6d38f94c4cd5db1fc858934a"
E_ESD = "acquisition-32b2a10e50a3ba1fd744c0cb"
E_RESET = "acquisition-88f595bfae507d094a32106f"
E_CLOCK = "acquisition-1566804addff639e8bf5d241"
E_LC = "acquisition-186acfd89ea560edffd6ff97"


def pin(
    pin_id: str,
    number: str,
    name: str,
    kind: PinElectricalType,
    evidence: str,
    domain: str | None = None,
) -> PhysicalPin:
    return PhysicalPin(
        pin_id=pin_id,
        numbers=[number],
        name=name,
        electrical_type=kind,
        voltage_domain=domain,
        evidence_ids=[evidence],
    )


def component(
    component_id: str,
    reference: str,
    value: str,
    sheet_id: str,
    pins: list[PhysicalPin],
    evidence: str,
    *,
    manufacturer: str | None = None,
    part_number: str | None = None,
    footprint: str | None = None,
) -> SchematicComponent:
    return SchematicComponent(
        component_id=component_id,
        reference=reference,
        value=value,
        sheet_id=sheet_id,
        manufacturer=manufacturer,
        part_number=part_number,
        footprint=footprint,
        pins=pins,
        evidence_ids=[evidence],
    )


def build_design() -> SchematicDesign:
    components: list[SchematicComponent] = []
    nets: dict[str, SchematicNet] = {}

    def add_net(
        net_id: str,
        name: str,
        net_class: NetClass,
        endpoints: list[tuple[str, str]],
        evidence: str,
        voltage: float | None = None,
    ) -> None:
        nets[net_id] = SchematicNet(
            net_id=net_id,
            name=name,
            net_class=net_class,
            endpoints=[PinReference(component_id=c, pin_id=p) for c, p in endpoints],
            nominal_voltage_v=voltage,
            evidence_ids=[evidence],
        )

    # The Phase 4 candidate deliberately contains only evidence-closed pins. Missing physical
    # circuitry is carried as critical unresolved state and therefore cannot be promoted to ready.
    for channel in range(1, 5):
        mic = f"mic-{channel}"
        esd = f"mic-esd-{channel}"
        afe = f"afe-{channel}"
        components.extend(
            [
                component(
                    mic,
                    f"J{channel}",
                    "Differential microphone connector envelope",
                    "microphone_afe",
                    [
                        pin("p", "1", "MIC_P", PinElectricalType.PASSIVE, E_ADAU),
                        pin("n", "2", "MIC_N", PinElectricalType.PASSIVE, E_ADAU),
                        pin("power", "3", "MIC_3V3", PinElectricalType.PASSIVE, E_ADAU),
                        pin("gnd", "4", "GND", PinElectricalType.PASSIVE, E_ADAU),
                    ],
                    E_ADAU,
                ),
                component(
                    esd,
                    f"D{channel}",
                    "TPD2E2U06DCKR",
                    "microphone_afe",
                    [
                        pin("p", "1", "IO1", PinElectricalType.PASSIVE, E_ESD),
                        pin("gnd", "2", "GND", PinElectricalType.PASSIVE, E_ESD),
                        pin("n", "3", "IO2", PinElectricalType.PASSIVE, E_ESD),
                    ],
                    E_ESD,
                    manufacturer="Texas Instruments",
                    part_number="TPD2E2U06DCKR",
                ),
                component(
                    afe,
                    f"U{channel}",
                    "THP210DR",
                    "microphone_afe",
                    [
                        pin("in_n", "1", "IN-", PinElectricalType.INPUT, E_THP, "3v3"),
                        pin("vocm", "2", "VOCM", PinElectricalType.INPUT, E_THP, "3v3"),
                        pin("vs_p", "3", "VS+", PinElectricalType.POWER_INPUT, E_THP, "3v3"),
                        pin("out_p", "4", "OUT+", PinElectricalType.OUTPUT, E_THP, "3v3"),
                        pin("out_n", "5", "OUT-", PinElectricalType.OUTPUT, E_THP, "3v3"),
                        pin("vs_n", "6", "VS-", PinElectricalType.POWER_INPUT, E_THP, "gnd"),
                        pin("pd", "7", "PD", PinElectricalType.INPUT, E_THP, "3v3"),
                        pin("in_p", "8", "IN+", PinElectricalType.INPUT, E_THP, "3v3"),
                    ],
                    E_THP,
                    manufacturer="Texas Instruments",
                    part_number="THP210DR",
                    footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                ),
            ]
        )
        add_net(
            f"mic{channel}-p",
            f"MIC{channel}_P",
            NetClass.ANALOG,
            [(mic, "p"), (esd, "p"), (afe, "in_p")],
            E_THP,
        )
        add_net(
            f"mic{channel}-n",
            f"MIC{channel}_N",
            NetClass.ANALOG,
            [(mic, "n"), (esd, "n"), (afe, "in_n")],
            E_THP,
        )

    adc_pins = [
        pin("vref", "2", "VREF", PinElectricalType.POWER_OUTPUT, E_ADAU),
        pin("pll", "3", "PLL_FILT", PinElectricalType.PASSIVE, E_ADAU),
        pin("reset", "6", "PD/RST", PinElectricalType.INPUT, E_ADAU, "3v3"),
        pin("mclk", "7", "MCLKIN", PinElectricalType.INPUT, E_ADAU, "3v3"),
        pin("dvdd", "10", "DVDD", PinElectricalType.POWER_OUTPUT, E_ADAU),
        pin("iovdd", "12", "IOVDD", PinElectricalType.POWER_INPUT, E_ADAU, "3v3"),
        pin("data", "13", "SDATAOUT1", PinElectricalType.OUTPUT, E_ADAU, "3v3"),
        pin("data2", "14", "SDATAOUT2", PinElectricalType.OUTPUT, E_ADAU, "3v3"),
        pin("fsync", "15", "LRCLK", PinElectricalType.INPUT, E_ADAU, "3v3"),
        pin("bclk", "16", "BCLK", PinElectricalType.INPUT, E_ADAU, "3v3"),
        pin("sda", "17", "SDA", PinElectricalType.BIDIRECTIONAL, E_ADAU, "3v3"),
        pin("scl", "18", "SCL", PinElectricalType.INPUT, E_ADAU, "3v3"),
    ]
    for channel, number in enumerate((33, 35, 37, 39), 1):
        adc_pins.append(
            pin(f"ain{channel}p", str(number), f"AIN{channel}P", PinElectricalType.INPUT, E_ADAU)
        )
        adc_pins.append(
            pin(
                f"ain{channel}n", str(number - 1), f"AIN{channel}N", PinElectricalType.INPUT, E_ADAU
            )
        )
    adc_pins.extend(
        [
            pin("avdd", "4,31,40", "AVDD", PinElectricalType.POWER_INPUT, E_ADAU, "3v3"),
            pin("agnd", "1,5,21,22,28,29,EP", "AGND", PinElectricalType.POWER_INPUT, E_ADAU, "gnd"),
            pin("dgnd", "11", "DGND", PinElectricalType.POWER_INPUT, E_ADAU, "gnd"),
            pin("mode", "9", "SA_MODE", PinElectricalType.INPUT, E_ADAU, "3v3"),
            pin("addr0", "19", "ADDR0", PinElectricalType.INPUT, E_ADAU, "3v3"),
            pin("addr1", "20", "ADDR1", PinElectricalType.INPUT, E_ADAU, "3v3"),
        ]
    )
    components.append(
        component(
            "adc",
            "U5",
            "ADAU1978WBCPZ",
            "adc",
            adc_pins,
            E_ADAU,
            manufacturer="Analog Devices",
            part_number="ADAU1978WBCPZ",
        )
    )

    components.extend(
        [
            component(
                "clock",
                "Y1",
                "ASDLJ-24.576MHZ-D-X-R-T",
                "clock",
                [
                    pin("oe", "1", "OE", PinElectricalType.INPUT, E_CLOCK, "1v8"),
                    pin("gnd", "2", "GND", PinElectricalType.POWER_INPUT, E_CLOCK, "gnd"),
                    pin("out", "3", "OUT", PinElectricalType.OUTPUT, E_CLOCK, "1v8"),
                    pin("vdd", "4", "VDD", PinElectricalType.POWER_INPUT, E_CLOCK, "1v8"),
                ],
                E_CLOCK,
                manufacturer="Abracon",
                part_number="ASDLJ-24.576MHZ-D-X-R-T",
            ),
            component(
                "clock-translator",
                "U6",
                "SN74AVC2T245RSWR",
                "clock",
                [
                    pin("dir2", "1", "DIR2", PinElectricalType.INPUT, E_TRANSLATOR, "1v8"),
                    pin("oe", "2", "OE", PinElectricalType.INPUT, E_TRANSLATOR, "1v8"),
                    pin("gnd", "3", "GND", PinElectricalType.POWER_INPUT, E_TRANSLATOR, "gnd"),
                    pin("b2", "4", "B2", PinElectricalType.OUTPUT, E_TRANSLATOR, "3v3"),
                    pin("b1", "5", "B1", PinElectricalType.OUTPUT, E_TRANSLATOR, "3v3"),
                    pin("vccb", "6", "VCCB", PinElectricalType.POWER_INPUT, E_TRANSLATOR, "3v3"),
                    pin("vcca", "7", "VCCA", PinElectricalType.POWER_INPUT, E_TRANSLATOR, "1v8"),
                    pin("a1", "8", "A1", PinElectricalType.INPUT, E_TRANSLATOR, "1v8"),
                    pin("a2", "9", "A2", PinElectricalType.INPUT, E_TRANSLATOR, "1v8"),
                    pin("dir1", "10", "DIR1", PinElectricalType.INPUT, E_TRANSLATOR, "1v8"),
                ],
                E_TRANSLATOR,
                manufacturer="Texas Instruments",
                part_number="SN74AVC2T245RSWR",
            ),
        ]
    )

    dsp_pins = [
        pin("clkin", "N01", "SYS_CLKIN0", PinElectricalType.INPUT, E_DSP_PINS, "1v8"),
        pin("bclk", "Y08", "DAI0_PIN01", PinElectricalType.OUTPUT, E_DSP_PINS, "3v3"),
        pin("fsync", "V09", "DAI0_PIN02", PinElectricalType.OUTPUT, E_DSP_PINS, "3v3"),
        pin("adc_data", "W09", "DAI0_PIN03", PinElectricalType.INPUT, E_DSP_PINS, "3v3"),
        pin("amp_data", "Y09", "DAI0_PIN04", PinElectricalType.OUTPUT, E_DSP_PINS, "3v3"),
        pin("scl", "U02", "PA_10/TWI0_SCL", PinElectricalType.OPEN_DRAIN, E_DSP_PINS, "3v3"),
        pin("sda", "V08", "PA_11/TWI0_SDA", PinElectricalType.BIDIRECTIONAL, E_DSP_PINS, "3v3"),
        pin("reset", "A09", "SYS_HWRST", PinElectricalType.INPUT, E_DSP_PINS, "3v3"),
        pin("vint", "VDD_INT_GROUP", "VDD_INT", PinElectricalType.POWER_INPUT, E_DSP_REF, "1v0"),
        pin("vext", "VDD_EXT_GROUP", "VDD_EXT", PinElectricalType.POWER_INPUT, E_DSP_REF, "3v3"),
        pin("vref", "VDD_REF_GROUP", "VDD_REF", PinElectricalType.POWER_INPUT, E_DSP_REF, "1v8"),
        pin("vana", "VDD_ANA_GROUP", "VDD_ANA", PinElectricalType.POWER_INPUT, E_DSP_REF, "1v8"),
        pin("gnd", "GND_GROUP", "GND", PinElectricalType.POWER_INPUT, E_DSP_REF, "gnd"),
    ]
    components.append(
        component(
            "dsp",
            "U7",
            "ADSP-21569BBCZ10",
            "dsp",
            dsp_pins,
            E_DSP_PINS,
            manufacturer="Analog Devices",
            part_number="ADSP-21569BBCZ10",
        )
    )

    components.append(
        component(
            "amplifier",
            "U11",
            "TAS6424QDKQRQ1",
            "class_d_output",
            [
                pin(
                    "pvdd",
                    "2,29,30,42,43,55,56",
                    "PVDD",
                    PinElectricalType.POWER_INPUT,
                    E_TAS,
                    "pvdd",
                ),
                pin("vbat", "3", "VBAT", PinElectricalType.POWER_INPUT, E_TAS, "pvdd"),
                pin("mclk", "12", "MCLK", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("bclk", "13", "SCLK", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("fsync", "14", "FSYNC", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("data", "15", "SDIN1", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("vdd", "19", "VDD", PinElectricalType.POWER_INPUT, E_TAS, "3v3"),
                pin("scl", "20", "SCL", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("sda", "21", "SDA", PinElectricalType.BIDIRECTIONAL, E_TAS, "3v3"),
                pin("standby", "24", "STANDBY", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin("mute", "25", "MUTE", PinElectricalType.INPUT, E_TAS, "3v3"),
                pin(
                    "gnd",
                    "1,11,17,18,28,33,36,39,46,49,52,EP",
                    "GND",
                    PinElectricalType.POWER_INPUT,
                    E_TAS,
                    "gnd",
                ),
            ],
            E_TAS,
            manufacturer="Texas Instruments",
            part_number="TAS6424QDKQRQ1",
        )
    )

    components.append(
        component(
            "pmic",
            "U10",
            "ADP5054ACPZ-R7",
            "power",
            [
                pin("vin", "PVIN_GROUP", "PVIN1-4", PinElectricalType.POWER_INPUT, E_ADP, "pvdd"),
                pin("v1", "SW1", "VOUT1_NETWORK", PinElectricalType.POWER_OUTPUT, E_ADP, "1v0"),
                pin("v3", "SW3", "VOUT3_NETWORK", PinElectricalType.POWER_OUTPUT, E_ADP, "3v3"),
                pin("v4", "SW4", "VOUT4_NETWORK", PinElectricalType.POWER_OUTPUT, E_ADP, "1v8"),
                pin("pg", "PWRGD", "PWRGD", PinElectricalType.OPEN_DRAIN, E_ADP, "3v3"),
                pin("gnd", "GND_GROUP", "GND", PinElectricalType.POWER_INPUT, E_ADP, "gnd"),
            ],
            E_ADP,
            manufacturer="Analog Devices",
            part_number="ADP5054ACPZ-R7",
        )
    )

    # Power and clock closure for the evidence-closed portion.
    gnd_endpoints = (
        [(f"mic-{c}", "gnd") for c in range(1, 5)]
        + [(f"mic-esd-{c}", "gnd") for c in range(1, 5)]
        + [(f"afe-{c}", "vs_n") for c in range(1, 5)]
        + [
            ("adc", "agnd"),
            ("adc", "dgnd"),
            ("clock", "gnd"),
            ("clock-translator", "gnd"),
            ("dsp", "gnd"),
            ("amplifier", "gnd"),
            ("pmic", "gnd"),
        ]
    )
    add_net("gnd", "GND", NetClass.GROUND, gnd_endpoints, E_DSP_REF, 0.0)
    rail3 = (
        [(f"mic-{c}", "power") for c in range(1, 5)]
        + [(f"afe-{c}", "vs_p") for c in range(1, 5)]
        + [(f"afe-{c}", "pd") for c in range(1, 5)]
        + [
            ("adc", "avdd"),
            ("adc", "iovdd"),
            ("clock-translator", "vccb"),
            ("dsp", "vext"),
            ("amplifier", "vdd"),
            ("pmic", "v3"),
        ]
    )
    add_net("rail-3v3", "+3V3", NetClass.POWER, rail3, E_ADP, 3.3)
    rail18 = [
        ("clock", "vdd"),
        ("clock", "oe"),
        ("clock-translator", "vcca"),
        ("clock-translator", "dir1"),
        ("clock-translator", "dir2"),
        ("dsp", "vref"),
        ("dsp", "vana"),
        ("pmic", "v4"),
    ]
    add_net("rail-1v8", "+1V8", NetClass.POWER, rail18, E_ADP, 1.8)
    add_net("rail-1v0", "+1V0", NetClass.POWER, [("dsp", "vint"), ("pmic", "v1")], E_ADP, 1.0)
    add_net(
        "pvdd",
        "PVDD_PROTECTED",
        NetClass.POWER,
        [("amplifier", "pvdd"), ("amplifier", "vbat"), ("pmic", "vin")],
        E_TAS,
        14.4,
    )
    add_net(
        "clock-raw",
        "MCLK_1V8",
        NetClass.CLOCK,
        [
            ("clock", "out"),
            ("clock-translator", "a1"),
            ("clock-translator", "a2"),
            ("dsp", "clkin"),
        ],
        E_CLOCK,
    )
    add_net(
        "mclk-adc",
        "MCLK_ADC_3V3",
        NetClass.CLOCK,
        [("clock-translator", "b1"), ("adc", "mclk")],
        E_TRANSLATOR,
    )
    add_net(
        "mclk-amp",
        "MCLK_AMP_3V3",
        NetClass.CLOCK,
        [("clock-translator", "b2"), ("amplifier", "mclk")],
        E_TRANSLATOR,
    )
    add_net(
        "clock-oe",
        "CLOCK_TRANSLATOR_OE_N",
        NetClass.POWER,
        [("clock-translator", "oe")],
        E_TRANSLATOR,
    )
    add_net(
        "tdm-bclk",
        "TDM_BCLK",
        NetClass.CLOCK,
        [("dsp", "bclk"), ("adc", "bclk"), ("amplifier", "bclk")],
        E_TAS,
    )
    add_net(
        "tdm-fsync",
        "TDM_FSYNC",
        NetClass.CLOCK,
        [("dsp", "fsync"), ("adc", "fsync"), ("amplifier", "fsync")],
        E_TAS,
    )
    add_net(
        "tdm-adc-data",
        "TDM_ADC_TO_DSP",
        NetClass.SIGNAL,
        [("adc", "data"), ("dsp", "adc_data")],
        E_ADAU,
    )
    add_net(
        "tdm-amp-data",
        "TDM_DSP_TO_AMP",
        NetClass.SIGNAL,
        [("dsp", "amp_data"), ("amplifier", "data")],
        E_TAS,
    )
    add_net(
        "i2c-scl",
        "I2C_SCL",
        NetClass.SIGNAL,
        [("dsp", "scl"), ("adc", "scl"), ("amplifier", "scl")],
        E_DSP_REF,
    )
    add_net(
        "i2c-sda",
        "I2C_SDA",
        NetClass.SIGNAL,
        [("dsp", "sda"), ("adc", "sda"), ("amplifier", "sda")],
        E_DSP_REF,
    )
    add_net("adc-reset", "ADC_RESET_N", NetClass.POWER, [("adc", "reset")], E_ADAU)
    add_net(
        "dsp-reset", "DSP_RESET_N", NetClass.SIGNAL, [("dsp", "reset"), ("pmic", "pg")], E_DSP_REF
    )
    add_net("amp-standby", "AMP_STANDBY", NetClass.POWER, [("amplifier", "standby")], E_TAS)
    add_net("amp-mute", "AMP_MUTE", NetClass.POWER, [("amplifier", "mute")], E_TAS)
    add_net("adc-data2-unused", "ADC_DATA2_UNUSED", NetClass.SIGNAL, [("adc", "data2")], E_ADAU)
    add_net(
        "adc-mode",
        "ADC_I2C_MODE",
        NetClass.POWER,
        [("adc", "mode"), ("adc", "addr0"), ("adc", "addr1")],
        E_ADAU,
    )
    add_net(
        "adc-vref",
        "ADC_VREF",
        NetClass.ANALOG,
        [("adc", "vref")] + [(f"afe-{c}", "vocm") for c in range(1, 5)],
        E_ADAU,
    )
    add_net("adc-pll", "ADC_PLL_FILTER", NetClass.ANALOG, [("adc", "pll")], E_ADAU)
    add_net("adc-dvdd", "ADC_DVDD_DECOUPLE", NetClass.POWER, [("adc", "dvdd")], E_ADAU, 1.8)
    for channel in range(1, 5):
        add_net(
            f"afe{channel}-outp",
            f"AFE{channel}_OUT_P",
            NetClass.ANALOG,
            [(f"afe-{channel}", "out_p"), ("adc", f"ain{channel}p")],
            E_THP,
        )
        add_net(
            f"afe{channel}-outn",
            f"AFE{channel}_OUT_N",
            NetClass.ANALOG,
            [(f"afe-{channel}", "out_n"), ("adc", f"ain{channel}n")],
            E_THP,
        )

    tdm_signals_adc = [
        InterfaceSignal(
            signal="mclk",
            net_id="mclk-adc",
            source_component_id="clock-translator",
            sink_component_ids=["adc"],
        ),
        InterfaceSignal(
            signal="bclk", net_id="tdm-bclk", source_component_id="dsp", sink_component_ids=["adc"]
        ),
        InterfaceSignal(
            signal="fsync",
            net_id="tdm-fsync",
            source_component_id="dsp",
            sink_component_ids=["adc"],
        ),
        InterfaceSignal(
            signal="data",
            net_id="tdm-adc-data",
            source_component_id="adc",
            sink_component_ids=["dsp"],
        ),
    ]
    tdm_signals_amp = [
        InterfaceSignal(
            signal="mclk",
            net_id="mclk-amp",
            source_component_id="clock-translator",
            sink_component_ids=["amplifier"],
        ),
        InterfaceSignal(
            signal="bclk",
            net_id="tdm-bclk",
            source_component_id="dsp",
            sink_component_ids=["amplifier"],
        ),
        InterfaceSignal(
            signal="fsync",
            net_id="tdm-fsync",
            source_component_id="dsp",
            sink_component_ids=["amplifier"],
        ),
        InterfaceSignal(
            signal="data",
            net_id="tdm-amp-data",
            source_component_id="dsp",
            sink_component_ids=["amplifier"],
        ),
    ]
    sheets = [
        SchematicSheet(
            sheet_id="root", name="ANC controller", file_name="anc_controller_v1.kicad_sch"
        )
    ]
    for sheet_id, name in [
        ("microphone_afe", "Microphone AFE"),
        ("adc", "ADC"),
        ("dsp", "DSP"),
        ("class_d_output", "Class-D output"),
        ("clock", "Clock"),
        ("power", "Power"),
        ("boot_debug_control", "Boot debug control"),
    ]:
        sheets.append(
            SchematicSheet(
                sheet_id=sheet_id,
                name=name,
                file_name=f"{sheet_id}.kicad_sch",
                parent_sheet_id="root",
            )
        )
    return SchematicDesign(
        design_id="anc_controller_v1",
        title="Four-channel ANC controller Phase 4 candidate",
        revision="P4-A",
        sheets=sheets,
        components=components,
        nets=list(nets.values()),
        rails=[
            SchematicRail(
                rail_id="1v0-core",
                net_id="rail-1v0",
                nominal_voltage_v=1.0,
                maximum_current_a=1.5,
                sequence_order=1,
                evidence_ids=[E_DSP],
            ),
            SchematicRail(
                rail_id="1v8-ref",
                net_id="rail-1v8",
                nominal_voltage_v=1.8,
                maximum_current_a=2.5,
                sequence_order=1,
                evidence_ids=[E_DSP],
            ),
            SchematicRail(
                rail_id="3v3-io",
                net_id="rail-3v3",
                nominal_voltage_v=3.3,
                maximum_current_a=2.5,
                sequence_order=1,
                evidence_ids=[E_ADP],
            ),
            SchematicRail(
                rail_id="pvdd",
                net_id="pvdd",
                nominal_voltage_v=14.4,
                maximum_current_a=10.0,
                sequence_order=0,
                evidence_ids=[E_TAS],
            ),
        ],
        interfaces=[
            SchematicInterface(
                interface_id="adc-tdm4",
                protocol="TDM4",
                roles={"dsp": InterfaceRole.MASTER, "adc": InterfaceRole.SLAVE},
                signals=tdm_signals_adc,
                sample_rate_hz=96_000,
                sample_width_bits=24,
                slot_width_bits=32,
                slot_count=4,
                evidence_ids=[E_ADAU],
            ),
            SchematicInterface(
                interface_id="amp-tdm4",
                protocol="TDM4",
                roles={"dsp": InterfaceRole.MASTER, "amplifier": InterfaceRole.SLAVE},
                signals=tdm_signals_amp,
                sample_rate_hz=96_000,
                sample_width_bits=24,
                slot_width_bits=32,
                slot_count=4,
                evidence_ids=[E_TAS],
            ),
        ],
        calculations=[
            EngineeringCalculation(
                calculation_id="tdm-bclk",
                formula="fBCLK=fS*slots*slot_width",
                inputs={"fS": 96000, "slots": 4, "slot_width": 32},
                result=float(tdm_bit_clock_hz(96_000, 4, 32)),
                unit="Hz",
                status=ValidationStatus.PASS,
                evidence_ids=[E_TAS],
            ),
            EngineeringCalculation(
                calculation_id="afe-high-pass",
                formula="fc=1/(2*pi*Rin*Cin)",
                inputs={"Rin_ohm": 2000, "Cin_f": 4.7e-6},
                result=differential_high_pass_hz(2000, 4.7e-6),
                unit="Hz",
                status=ValidationStatus.WARNING,
                assumptions=[
                    "20 dB nominal gain envelope; final microphone sensitivity is unknown"
                ],
                evidence_ids=[E_THP],
            ),
            EngineeringCalculation(
                calculation_id="adp5054-fb-3v3",
                formula="Rtop=Rbot*(Vout/Vref-1)",
                inputs={"Rbot_ohm": 10000, "Vout_v": 3.3, "Vref_v": 0.8},
                result=adp5054_feedback_top_ohms(3.3, 10000),
                unit="ohm",
                status=ValidationStatus.PASS,
                evidence_ids=[E_ADP],
            ),
            EngineeringCalculation(
                calculation_id="adp5054-l1-1v0",
                formula="L=((Vin-Vout)*D)/(0.35*Iout*fSW)",
                inputs={"Vin_v": 15.5, "Vout_v": 1.0, "Iout_a": 1.5, "fSW_hz": 500000},
                result=adp5054_inductor_h(15.5, 1.0, 1.5, 500000) * 1e6,
                unit="uH",
                status=ValidationStatus.PASS,
                evidence_ids=[E_ADP],
            ),
        ],
        evidence_ids=[
            E_ADAU,
            E_DSP,
            E_DSP_PINS,
            E_DSP_REF,
            E_TAS,
            E_ADP,
            E_THP,
            E_TRANSLATOR,
            E_ESD,
            E_RESET,
            E_CLOCK,
            E_LC,
        ],
        unresolved_items=[
            SchematicUnresolvedItem(
                item_id="kicad-electrical-symbol-emission",
                description=(
                    "The current deterministic backend emits KiCad hierarchy and typed-IR "
                    "annotations, but not electrically connected symbol instances and wires; "
                    "the output is not an electrically complete KiCad schematic."
                ),
                critical=True,
            ),
            SchematicUnresolvedItem(
                item_id="dsp-full-power-ball-expansion",
                description=(
                    "ADSP-21569 signal balls are BSDL-validated, but grouped power/ground "
                    "placeholders must be expanded to every EV-21569-SOM-validated ball "
                    "before fabrication-grade schematic review."
                ),
                critical=True,
                affected_component_ids=["dsp"],
            ),
            SchematicUnresolvedItem(
                item_id="afe-passive-population",
                description=(
                    "The typed calculations identify a 20 dB/16.93 Hz provisional AFE "
                    "envelope, but feedback, coupling, RF-filter, and VREF-buffer parts are "
                    "not instantiated because microphone sensitivity and overload "
                    "requirements remain unknown."
                ),
                critical=True,
                affected_component_ids=["afe-1", "afe-2", "afe-3", "afe-4"],
            ),
            SchematicUnresolvedItem(
                item_id="adp5054-external-network",
                description=(
                    "Feedback and inductor targets are calculated, but channel compensation, "
                    "low-side MOSFET, bootstrap, input/output capacitors, current-limit "
                    "straps, and exact sequencing supervisor network are not instantiated."
                ),
                critical=True,
                affected_component_ids=["pmic"],
            ),
            SchematicUnresolvedItem(
                item_id="boot-jtag-reset-population",
                description=(
                    "Official EV-21569-SOM evidence was acquired, but SPI flash, boot straps, "
                    "reset supervisor, and JTAG connector are not yet instantiated in the "
                    "emitted schematic."
                ),
                critical=True,
                affected_component_ids=["dsp"],
            ),
            SchematicUnresolvedItem(
                item_id="class-d-output-network",
                description=(
                    "The documented 3.3 uH plus 1 uF output-filter envelope has not been "
                    "instantiated with bootstrap, bypass, AREF/VREG/VCOM/GVDD/AVDD networks "
                    "and speaker connectors."
                ),
                critical=True,
                affected_component_ids=["amplifier"],
            ),
            SchematicUnresolvedItem(
                item_id="power-input-protection",
                description=(
                    "No evidence-selected connector, fuse, reverse-polarity device, or "
                    "surge clamp has been instantiated for the regulated 4.5 V to 15.5 V "
                    "input envelope."
                ),
                critical=True,
                affected_component_ids=["pmic", "amplifier"],
            ),
        ],
    )


if __name__ == "__main__":
    result = KiCadSchematicBackend().generate(build_design(), OUTPUT)
    print(result.model_dump_json(indent=2))
