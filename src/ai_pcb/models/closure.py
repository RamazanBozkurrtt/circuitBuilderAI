from __future__ import annotations

from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel
from ai_pcb.models.validation import ValidationStatus


class DesignVariableKind(StrEnum):
    USER_CONSTRAINT = "USER_CONSTRAINT"
    ENGINEERING_DESIGN_VARIABLE = "ENGINEERING_DESIGN_VARIABLE"


class DesignVariableStatus(StrEnum):
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
    RESOLVED = "RESOLVED"
    DESIGN_ENVELOPE = "DESIGN_ENVELOPE"
    UNRESOLVED = "UNRESOLVED"


class DesignEnvelopeScenario(StrictModel):
    scenario_id: Identifier
    label: NonEmptyString
    value: JsonValue
    unit: str | None = None
    conditions: list[NonEmptyString] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)


class DesignEnvelope(StrictModel):
    envelope_id: Identifier
    scenarios: list[DesignEnvelopeScenario] = Field(min_length=1)
    assumptions: list[NonEmptyString] = Field(min_length=1)
    selected_scenario_id: Identifier | None = None

    @model_validator(mode="after")
    def selected_scenario_exists(self) -> DesignEnvelope:
        if self.selected_scenario_id is not None and self.selected_scenario_id not in {
            scenario.scenario_id for scenario in self.scenarios
        }:
            raise ValueError("selected design-envelope scenario does not exist")
        return self


class DesignVariable(StrictModel):
    variable_id: Identifier
    master_spec_path: NonEmptyString | None = None
    kind: DesignVariableKind
    status: DesignVariableStatus
    rationale: NonEmptyString
    resolution: EngineeringValue | None = None
    envelope: DesignEnvelope | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def closure_is_explicit(self) -> DesignVariable:
        if self.status is DesignVariableStatus.RESOLVED:
            if self.kind is not DesignVariableKind.ENGINEERING_DESIGN_VARIABLE:
                raise ValueError("the system cannot resolve a USER_CONSTRAINT")
            if self.resolution is None or self.resolution.status is ValueStatus.UNKNOWN:
                raise ValueError("resolved design variables require a known engineering value")
        elif self.resolution is not None:
            raise ValueError("only resolved design variables may contain a resolution")
        if (self.status is DesignVariableStatus.DESIGN_ENVELOPE) != (self.envelope is not None):
            raise ValueError("DESIGN_ENVELOPE status and envelope must be supplied together")
        return self


class ReadinessStatus(StrEnum):
    READY_FOR_PHASE_4 = "READY_FOR_PHASE_4"
    NOT_READY_FOR_PHASE_4 = "NOT_READY_FOR_PHASE_4"


class ReadinessCriterion(StrictModel):
    criterion_id: Identifier
    description: NonEmptyString
    status: ValidationStatus
    rationale: NonEmptyString
    evidence_ids: list[Identifier] = Field(default_factory=list)


class Phase4ReadinessAssessment(StrictModel):
    status: ReadinessStatus
    criteria: list[ReadinessCriterion] = Field(min_length=1)
    blockers: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def readiness_matches_criteria(self) -> Phase4ReadinessAssessment:
        blocked = any(
            criterion.status in {ValidationStatus.FAIL, ValidationStatus.UNKNOWN}
            for criterion in self.criteria
        )
        if blocked != (self.status is ReadinessStatus.NOT_READY_FOR_PHASE_4):
            raise ValueError("readiness status must reflect failed or unknown gate criteria")
        if blocked and not self.blockers:
            raise ValueError("a blocked readiness gate requires explicit blockers")
        return self


class MicrophoneTechnologyOption(StrictModel):
    option_id: Identifier
    technology: NonEmptyString
    interface: NonEmptyString
    selected: bool = False
    rationale: NonEmptyString
    evidence_ids: list[Identifier] = Field(default_factory=list)


class MicrophoneFrontEnd(StrictModel):
    architecture_id: Identifier
    channel_count: int = Field(ge=1)
    selected_technology: NonEmptyString
    selected_interface: NonEmptyString
    adc_part_number: NonEmptyString
    adc_topology: NonEmptyString
    analog_front_end_requirements: list[NonEmptyString] = Field(min_length=1)
    options: list[MicrophoneTechnologyOption] = Field(min_length=2)
    unresolved_terms: list[NonEmptyString] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def one_option_is_selected(self) -> MicrophoneFrontEnd:
        if sum(option.selected for option in self.options) != 1:
            raise ValueError("microphone front end requires exactly one selected technology")
        return self


class ClockSignal(StrictModel):
    signal_id: Identifier
    source: NonEmptyString
    sinks: list[NonEmptyString] = Field(min_length=1)
    frequency_hz: int = Field(gt=0)
    relationship: NonEmptyString
    divider: NonEmptyString
    jitter_sensitive: bool = False
    evidence_ids: list[Identifier] = Field(min_length=1)


class ProvisionalClockTree(StrictModel):
    tree_id: Identifier
    source_frequency_hz: int = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    audio_master: NonEmptyString
    signals: list[ClockSignal] = Field(min_length=3)
    synchronization_strategy: NonEmptyString
    jitter_strategy: list[NonEmptyString] = Field(min_length=1)
    reset_strategy: list[NonEmptyString] = Field(min_length=1)
    evidence_ids: list[Identifier] = Field(min_length=1)


class ProvisionalPowerRail(StrictModel):
    rail_id: Identifier
    nominal_voltage: EngineeringValue
    source: NonEmptyString
    consumers: list[NonEmptyString] = Field(min_length=1)
    regulator_class: NonEmptyString
    provisional_regulator: str | None = None
    current_budget: EngineeringValue
    noise_sensitive: bool = False
    sequence: NonEmptyString
    evidence_ids: list[Identifier] = Field(min_length=1)


class ProvisionalPowerTree(StrictModel):
    tree_id: Identifier
    input_envelope: DesignEnvelope
    rails: list[ProvisionalPowerRail] = Field(min_length=3)
    known_minimum_power: EngineeringValue
    estimated_design_power: EngineeringValue
    unknown_contributors: list[NonEmptyString] = Field(default_factory=list)
    sequencing_strategy: list[NonEmptyString] = Field(min_length=1)
    thermal_implications: list[NonEmptyString] = Field(min_length=1)
    evidence_ids: list[Identifier] = Field(min_length=1)
