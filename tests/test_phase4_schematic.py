from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_pcb.evidence.bsdl import parse_boundary_scan_pin_map
from ai_pcb.kicad.backend import KiCadSchematicBackend
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
)
from ai_pcb.models.validation import ValidationStatus
from ai_pcb.schematic.calculations import (
    adp5054_feedback_top_ohms,
    adp5054_inductor_h,
    differential_high_pass_hz,
    tdm_bit_clock_hz,
)
from ai_pcb.validation.schematic import validate_schematic_design


def _pin(pin_id: str, number: str, kind: PinElectricalType) -> PhysicalPin:
    return PhysicalPin(
        pin_id=pin_id,
        numbers=[number],
        name=pin_id,
        electrical_type=kind,
        evidence_ids=["evidence-pin-map"],
    )


def _design() -> SchematicDesign:
    source = SchematicComponent(
        component_id="clock-source",
        reference="Y1",
        value="24.576 MHz",
        sheet_id="clock",
        pins=[
            _pin("out", "3", PinElectricalType.OUTPUT),
            _pin("vdd", "4", PinElectricalType.POWER_INPUT),
            _pin("gnd", "2", PinElectricalType.POWER_INPUT),
        ],
        evidence_ids=["evidence-clock"],
    )
    sink = SchematicComponent(
        component_id="audio-sink",
        reference="U1",
        value="documented-audio-sink",
        sheet_id="audio",
        pins=[
            _pin("mclk", "1", PinElectricalType.INPUT),
            _pin("bclk", "2", PinElectricalType.INPUT),
            _pin("fsync", "3", PinElectricalType.INPUT),
            _pin("data", "4", PinElectricalType.INPUT),
            _pin("vdd", "5", PinElectricalType.POWER_INPUT),
            _pin("gnd", "6", PinElectricalType.POWER_INPUT),
        ],
        evidence_ids=["evidence-audio"],
    )
    dsp = SchematicComponent(
        component_id="dsp",
        reference="U2",
        value="documented-dsp",
        sheet_id="audio",
        pins=[
            _pin("bclk", "A1", PinElectricalType.OUTPUT),
            _pin("fsync", "A2", PinElectricalType.OUTPUT),
            _pin("data", "A3", PinElectricalType.OUTPUT),
            _pin("vdd", "A4", PinElectricalType.POWER_INPUT),
            _pin("gnd", "A5", PinElectricalType.POWER_INPUT),
        ],
        evidence_ids=["evidence-dsp"],
    )
    nets = [
        SchematicNet(
            net_id="mclk",
            name="AUDIO_MCLK",
            net_class=NetClass.CLOCK,
            endpoints=[
                PinReference(component_id="clock-source", pin_id="out"),
                PinReference(component_id="audio-sink", pin_id="mclk"),
            ],
            evidence_ids=["evidence-clock"],
        ),
        SchematicNet(
            net_id="bclk",
            name="AUDIO_BCLK",
            net_class=NetClass.CLOCK,
            endpoints=[
                PinReference(component_id="dsp", pin_id="bclk"),
                PinReference(component_id="audio-sink", pin_id="bclk"),
            ],
            evidence_ids=["evidence-tdm"],
        ),
        SchematicNet(
            net_id="fsync",
            name="AUDIO_FSYNC",
            net_class=NetClass.CLOCK,
            endpoints=[
                PinReference(component_id="dsp", pin_id="fsync"),
                PinReference(component_id="audio-sink", pin_id="fsync"),
            ],
            evidence_ids=["evidence-tdm"],
        ),
        SchematicNet(
            net_id="data",
            name="AUDIO_DATA",
            net_class=NetClass.SIGNAL,
            endpoints=[
                PinReference(component_id="dsp", pin_id="data"),
                PinReference(component_id="audio-sink", pin_id="data"),
            ],
            evidence_ids=["evidence-tdm"],
        ),
        SchematicNet(
            net_id="3v3",
            name="+3V3",
            net_class=NetClass.POWER,
            nominal_voltage_v=3.3,
            endpoints=[
                PinReference(component_id="clock-source", pin_id="vdd"),
                PinReference(component_id="audio-sink", pin_id="vdd"),
                PinReference(component_id="dsp", pin_id="vdd"),
            ],
            evidence_ids=["evidence-power"],
        ),
        SchematicNet(
            net_id="gnd",
            name="GND",
            net_class=NetClass.GROUND,
            nominal_voltage_v=0,
            endpoints=[
                PinReference(component_id="clock-source", pin_id="gnd"),
                PinReference(component_id="audio-sink", pin_id="gnd"),
                PinReference(component_id="dsp", pin_id="gnd"),
            ],
            evidence_ids=["evidence-power"],
        ),
    ]
    return SchematicDesign(
        design_id="typed-test-design",
        title="Typed test design",
        revision="A",
        sheets=[
            SchematicSheet(sheet_id="root", name="Root", file_name="typed_test_design.kicad_sch"),
            SchematicSheet(
                sheet_id="clock", name="Clock", file_name="clock.kicad_sch", parent_sheet_id="root"
            ),
            SchematicSheet(
                sheet_id="audio", name="Audio", file_name="audio.kicad_sch", parent_sheet_id="root"
            ),
        ],
        components=[source, sink, dsp],
        nets=nets,
        rails=[
            SchematicRail(
                rail_id="rail-3v3",
                net_id="3v3",
                nominal_voltage_v=3.3,
                maximum_current_a=1.0,
                sequence_order=1,
                evidence_ids=["evidence-power"],
            )
        ],
        interfaces=[
            SchematicInterface(
                interface_id="tdm4-test",
                protocol="TDM4",
                roles={"dsp": InterfaceRole.MASTER, "audio-sink": InterfaceRole.SLAVE},
                signals=[
                    InterfaceSignal(
                        signal="mclk",
                        net_id="mclk",
                        source_component_id="clock-source",
                        sink_component_ids=["audio-sink"],
                    ),
                    InterfaceSignal(
                        signal="bclk",
                        net_id="bclk",
                        source_component_id="dsp",
                        sink_component_ids=["audio-sink"],
                    ),
                    InterfaceSignal(
                        signal="fsync",
                        net_id="fsync",
                        source_component_id="dsp",
                        sink_component_ids=["audio-sink"],
                    ),
                    InterfaceSignal(
                        signal="data",
                        net_id="data",
                        source_component_id="dsp",
                        sink_component_ids=["audio-sink"],
                    ),
                ],
                sample_rate_hz=96_000,
                sample_width_bits=24,
                slot_width_bits=32,
                slot_count=4,
                evidence_ids=["evidence-tdm"],
            )
        ],
        calculations=[
            EngineeringCalculation(
                calculation_id="tdm-bclk",
                formula="fBCLK=fS*slots*slot_width",
                inputs={"sample_rate_hz": 96000, "slots": 4, "slot_width_bits": 32},
                result=12_288_000,
                unit="Hz",
                status=ValidationStatus.PASS,
                evidence_ids=["evidence-tdm"],
            )
        ],
        evidence_ids=["evidence-power", "evidence-tdm"],
    )


def test_schematic_ir_validation_and_interface_consistency() -> None:
    results = validate_schematic_design(_design())
    assert all(result.status is ValidationStatus.PASS for result in results)


def test_invalid_or_unknown_pin_reference_is_rejected() -> None:
    raw = _design().model_dump(mode="python")
    raw["nets"][0]["endpoints"][0]["pin_id"] = "invented-pin"
    with pytest.raises(ValidationError, match="unknown component pin"):
        SchematicDesign.model_validate(raw)


def test_evidence_backed_component_and_pin_are_required() -> None:
    with pytest.raises(ValidationError):
        PhysicalPin(
            pin_id="p",
            numbers=["1"],
            name="P",
            electrical_type=PinElectricalType.INPUT,
            evidence_ids=[],
        )


def test_power_and_afe_calculations_are_deterministic() -> None:
    assert tdm_bit_clock_hz(96_000, 4, 32) == 12_288_000
    assert adp5054_feedback_top_ohms(3.3, 10_000) == pytest.approx(31_250)
    assert adp5054_inductor_h(15.5, 1.0, 1.5, 500_000) == pytest.approx(3.564e-6, rel=1e-3)
    assert differential_high_pass_hz(2_000, 4.7e-6) == pytest.approx(16.93, rel=1e-3)


def test_official_adsp_bsdl_pin_map_integrity() -> None:
    path = next(Path("knowledge/boundary_scan/analog_devices").glob("*.bsdl"))
    pin_map = parse_boundary_scan_pin_map(
        path,
        part_number="ADSP21569",
        acquisition_id="acquisition-29511604a3f976beb37bb6d3",
        expected_sha256="06d87db0de185714250360489f78330732a38d20a32e7bb08df4e711a1430562",
    )
    assert pin_map.pins["SYS_CLKIN0"] == "N01"
    assert pin_map.pins["DAI0_PIN01"] == "Y08"
    assert pin_map.pins["JTG_TCK"] == "B11"


def test_kicad_generation_is_deterministic_and_has_no_raw_llm_path(tmp_path: Path) -> None:
    backend = KiCadSchematicBackend()
    first = backend.generate(_design(), tmp_path / "first")
    second = backend.generate(_design(), tmp_path / "second")
    assert (
        Path(first.root_schematic_file).read_bytes()
        == Path(second.root_schematic_file).read_bytes()
    )
    assert Path(first.ir_file).read_bytes() == Path(second.ir_file).read_bytes()
    with pytest.raises(TypeError, match="validated SchematicDesign"):
        backend.generate(_design().model_dump(), tmp_path / "raw")  # type: ignore[arg-type]
