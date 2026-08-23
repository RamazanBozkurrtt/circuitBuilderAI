from __future__ import annotations

from collections import Counter

from ai_pcb.models.schematic import (
    InterfaceRole,
    NetClass,
    PinElectricalType,
    SchematicDesign,
)
from ai_pcb.models.validation import ValidationResult, ValidationSeverity, ValidationStatus


def _result(
    result_id: str,
    status: ValidationStatus,
    summary: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.CRITICAL,
    details: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> ValidationResult:
    return ValidationResult(
        result_id=result_id,
        validator="schematic_ir",
        status=status,
        severity=severity,
        summary=summary,
        details=details or [],
        evidence_ids=evidence_ids or [],
    )


def validate_schematic_design(design: SchematicDesign) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    refs = [component.reference for component in design.components]
    duplicates = sorted(reference for reference, count in Counter(refs).items() if count > 1)
    results.append(
        _result(
            "schematic-reference-integrity",
            ValidationStatus.FAIL if duplicates else ValidationStatus.PASS,
            "Duplicate component references" if duplicates else "Component references are unique",
            details=duplicates,
        )
    )

    unevidenced = sorted(
        component.reference
        for component in design.components
        if not component.evidence_ids or any(not pin.evidence_ids for pin in component.pins)
    )
    results.append(
        _result(
            "schematic-component-evidence",
            ValidationStatus.FAIL if unevidenced else ValidationStatus.PASS,
            (
                "Components or pin maps lack evidence"
                if unevidenced
                else "Every component and pin map is evidence-backed"
            ),
            details=unevidenced,
        )
    )

    critical = sorted(item.item_id for item in design.unresolved_items if item.critical)
    results.append(
        _result(
            "schematic-critical-unresolved",
            ValidationStatus.UNKNOWN if critical else ValidationStatus.PASS,
            (
                "Critical schematic items remain unresolved"
                if critical
                else "No critical schematic item is unresolved"
            ),
            details=critical,
        )
    )

    net_by_id = {net.net_id: net for net in design.nets}
    pin_by_key = {
        (component.component_id, pin.pin_id): pin
        for component in design.components
        for pin in component.pins
    }
    contention: list[str] = []
    undriven: list[str] = []
    for net in design.nets:
        types = [
            pin_by_key[(endpoint.component_id, endpoint.pin_id)].electrical_type
            for endpoint in net.endpoints
        ]
        drivers = sum(
            item in {PinElectricalType.OUTPUT, PinElectricalType.OPEN_DRAIN} for item in types
        )
        if drivers > 1 and net.net_class not in {NetClass.POWER, NetClass.GROUND}:
            contention.append(net.name)
        if (
            net.net_class in {NetClass.CLOCK, NetClass.SIGNAL}
            and PinElectricalType.INPUT in types
            and not any(
                item
                in {
                    PinElectricalType.OUTPUT,
                    PinElectricalType.BIDIRECTIONAL,
                    PinElectricalType.OPEN_DRAIN,
                }
                for item in types
            )
        ):
            undriven.append(net.name)
    bad_nets = sorted(set(contention + undriven))
    results.append(
        _result(
            "schematic-net-directions",
            ValidationStatus.FAIL if bad_nets else ValidationStatus.PASS,
            "Signal direction conflict or undriven net"
            if bad_nets
            else "Net directions are consistent",
            details=bad_nets,
        )
    )

    audio_errors: list[str] = []
    for interface in design.interfaces:
        if interface.protocol != "TDM4":
            continue
        if (
            interface.sample_rate_hz != 96_000
            or interface.sample_width_bits != 24
            or interface.slot_width_bits != 32
            or interface.slot_count != 4
        ):
            audio_errors.append(interface.interface_id)
        masters = sum(role is InterfaceRole.MASTER for role in interface.roles.values())
        if masters != 1:
            audio_errors.append(interface.interface_id)
        signal_names = {signal.signal for signal in interface.signals}
        if not {"mclk", "bclk", "fsync", "data"}.issubset(signal_names):
            audio_errors.append(interface.interface_id)
    results.append(
        _result(
            "schematic-tdm4-closure",
            ValidationStatus.FAIL if audio_errors else ValidationStatus.PASS,
            (
                "TDM4 interface settings are inconsistent"
                if audio_errors
                else "TDM4 interfaces close at 96 kHz, 24-bit in four 32-bit slots"
            ),
            details=sorted(set(audio_errors)),
        )
    )

    rail_errors = sorted(
        rail.rail_id
        for rail in design.rails
        if net_by_id[rail.net_id].nominal_voltage_v != rail.nominal_voltage_v
    )
    results.append(
        _result(
            "schematic-rail-consistency",
            ValidationStatus.FAIL if rail_errors else ValidationStatus.PASS,
            "Rail and net voltages differ" if rail_errors else "Rail declarations match power nets",
            details=rail_errors,
        )
    )
    return results


def schematic_can_enter_verification(design: SchematicDesign) -> bool:
    return not any(result.blocks_progression for result in validate_schematic_design(design))
