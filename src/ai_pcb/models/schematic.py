from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel
from ai_pcb.models.validation import ValidationStatus


class PinElectricalType(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    PASSIVE = "PASSIVE"
    POWER_INPUT = "POWER_INPUT"
    POWER_OUTPUT = "POWER_OUTPUT"
    OPEN_DRAIN = "OPEN_DRAIN"
    NO_CONNECT = "NO_CONNECT"


class NetClass(StrEnum):
    SIGNAL = "SIGNAL"
    CLOCK = "CLOCK"
    ANALOG = "ANALOG"
    POWER = "POWER"
    GROUND = "GROUND"
    CLASS_D_OUTPUT = "CLASS_D_OUTPUT"


class InterfaceRole(StrEnum):
    MASTER = "MASTER"
    SLAVE = "SLAVE"
    CONTROLLER = "CONTROLLER"
    TARGET = "TARGET"
    SOURCE = "SOURCE"
    SINK = "SINK"


class PhysicalPin(StrictModel):
    pin_id: Identifier
    numbers: list[NonEmptyString] = Field(min_length=1)
    name: NonEmptyString
    electrical_type: PinElectricalType
    voltage_domain: Identifier | None = None
    evidence_ids: list[Identifier] = Field(min_length=1)


class SchematicComponent(StrictModel):
    component_id: Identifier
    reference: NonEmptyString
    value: NonEmptyString
    sheet_id: Identifier
    manufacturer: NonEmptyString | None = None
    part_number: NonEmptyString | None = None
    footprint: str | None = None
    pins: list[PhysicalPin] = Field(min_length=1)
    evidence_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def pins_are_unique(self) -> SchematicComponent:
        ids = [pin.pin_id for pin in self.pins]
        numbers = [number for pin in self.pins for number in pin.numbers]
        if len(ids) != len(set(ids)):
            raise ValueError("component pin ids must be unique")
        if len(numbers) != len(set(numbers)):
            raise ValueError("physical pin numbers must be unique within a component")
        return self


class PinReference(StrictModel):
    component_id: Identifier
    pin_id: Identifier


class SchematicNet(StrictModel):
    net_id: Identifier
    name: NonEmptyString
    net_class: NetClass
    endpoints: list[PinReference] = Field(min_length=1)
    nominal_voltage_v: float | None = Field(default=None, ge=0)
    evidence_ids: list[Identifier] = Field(min_length=1)


class SchematicRail(StrictModel):
    rail_id: Identifier
    net_id: Identifier
    nominal_voltage_v: float = Field(gt=0)
    maximum_current_a: float = Field(gt=0)
    sequence_order: int = Field(ge=0)
    evidence_ids: list[Identifier] = Field(min_length=1)


class InterfaceSignal(StrictModel):
    signal: Identifier
    net_id: Identifier
    source_component_id: Identifier
    sink_component_ids: list[Identifier] = Field(min_length=1)


class SchematicInterface(StrictModel):
    interface_id: Identifier
    protocol: NonEmptyString
    roles: dict[Identifier, InterfaceRole]
    signals: list[InterfaceSignal] = Field(min_length=1)
    sample_rate_hz: int | None = Field(default=None, gt=0)
    sample_width_bits: int | None = Field(default=None, gt=0)
    slot_width_bits: int | None = Field(default=None, gt=0)
    slot_count: int | None = Field(default=None, gt=0)
    evidence_ids: list[Identifier] = Field(min_length=1)


class EngineeringCalculation(StrictModel):
    calculation_id: Identifier
    formula: NonEmptyString
    inputs: dict[str, float | int | str]
    result: float
    unit: NonEmptyString
    status: ValidationStatus
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(min_length=1)


class SchematicSheet(StrictModel):
    sheet_id: Identifier
    name: NonEmptyString
    file_name: NonEmptyString
    parent_sheet_id: Identifier | None = None


class SchematicUnresolvedItem(StrictModel):
    item_id: Identifier
    description: NonEmptyString
    critical: bool
    affected_component_ids: list[Identifier] = Field(default_factory=list)


class SchematicDesign(StrictModel):
    design_id: Identifier
    title: NonEmptyString
    revision: NonEmptyString
    sheets: list[SchematicSheet] = Field(min_length=1)
    components: list[SchematicComponent] = Field(min_length=1)
    nets: list[SchematicNet] = Field(min_length=1)
    rails: list[SchematicRail] = Field(min_length=1)
    interfaces: list[SchematicInterface] = Field(min_length=1)
    no_connects: list[PinReference] = Field(default_factory=list)
    calculations: list[EngineeringCalculation] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(min_length=1)
    unresolved_items: list[SchematicUnresolvedItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_closed(self) -> SchematicDesign:
        sheet_ids = [sheet.sheet_id for sheet in self.sheets]
        component_ids = [component.component_id for component in self.components]
        net_ids = [net.net_id for net in self.nets]
        if len(sheet_ids) != len(set(sheet_ids)):
            raise ValueError("sheet ids must be unique")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component ids must be unique")
        if len(net_ids) != len(set(net_ids)):
            raise ValueError("net ids must be unique")
        sheets = set(sheet_ids)
        if any(component.sheet_id not in sheets for component in self.components):
            raise ValueError("component references an unknown sheet")
        pins = {
            (component.component_id, pin.pin_id): pin
            for component in self.components
            for pin in component.pins
        }
        endpoints = [endpoint for net in self.nets for endpoint in net.endpoints]
        endpoints.extend(self.no_connects)
        unknown = [
            endpoint
            for endpoint in endpoints
            if (endpoint.component_id, endpoint.pin_id) not in pins
        ]
        if unknown:
            raise ValueError("net or no-connect references an unknown component pin")
        keys = [(item.component_id, item.pin_id) for item in endpoints]
        if len(keys) != len(set(keys)):
            raise ValueError("a component pin may occur on exactly one net or no-connect")
        missing = sorted(set(pins) - set(keys))
        if missing:
            raise ValueError(f"component pins require a net or explicit no-connect: {missing}")
        nets = set(net_ids)
        if any(rail.net_id not in nets for rail in self.rails):
            raise ValueError("rail references an unknown net")
        for interface in self.interfaces:
            if any(signal.net_id not in nets for signal in interface.signals):
                raise ValueError("interface signal references an unknown net")
        return self

    @property
    def has_critical_unresolved_items(self) -> bool:
        return any(item.critical for item in self.unresolved_items)
