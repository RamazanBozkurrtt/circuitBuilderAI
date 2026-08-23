from __future__ import annotations

from pydantic import JsonValue

from ai_pcb.models.architecture import ConstraintKind
from ai_pcb.models.components import ComponentCategory, ComponentRequirement
from ai_pcb.models.spec import MasterSpec, Requirement, RequirementStatus
from ai_pcb.specializations.models import ResolvedSpecializationContext

_HARD_FACTS = {
    "channel_count",
    "input_channels",
    "output_channels",
    "audio_input_capacity",
    "audio_output_capacity",
    "audio_interfaces",
    "clocking",
    "speaker_load",
    "input_voltage_range",
    "output_voltage",
}


class ComponentRequirementDeriver:
    def derive(
        self, spec: MasterSpec, context: ResolvedSpecializationContext
    ) -> list[ComponentRequirement]:
        requirements: list[ComponentRequirement] = []
        for category_guidance in context.component_categories:
            category = ComponentCategory(category_guidance.category)
            for fact in category_guidance.required_facts:
                source = self._source(category, fact)
                master_requirement = (
                    spec.sections()[source[0]].requirements.get(source[1]) if source else None
                )
                status, value, unit, critical = self._resolved_value(
                    category, fact, master_requirement, spec
                )
                requirements.append(
                    ComponentRequirement(
                        requirement_id=f"{category.value.lower()}.{fact}",
                        category=category,
                        attribute=fact,
                        description=(
                            f"{category.value.replace('_', ' ').title()}: "
                            f"{fact.replace('_', ' ')}"
                        ),
                        kind=(
                            ConstraintKind.HARD_CONSTRAINT
                            if fact in _HARD_FACTS
                            else ConstraintKind.OPTIMIZATION_OBJECTIVE
                        ),
                        status=status,
                        value=value,
                        unit=unit,
                        critical=critical,
                        source_requirements=(
                            [f"{source[0]}.{source[1]}"] if source is not None else []
                        ),
                        declared_by_specializations=[
                            definition.id
                            for definition in context.resolved
                            if category_guidance in definition.component_categories
                        ],
                    )
                )
        return requirements

    @staticmethod
    def _source(category: ComponentCategory, fact: str) -> tuple[str, str] | None:
        if fact in {"channel_count", "input_channels", "audio_input_capacity"} and (
            category
            in {
                ComponentCategory.ADC,
                ComponentCategory.AUDIO_CODEC,
                ComponentCategory.DSP_PROCESSOR,
            }
        ):
            return ("audio", "microphone_input_channels")
        if fact in {"channel_count", "output_channels", "audio_output_capacity"} and (
            category
            in {
                ComponentCategory.DAC,
                ComponentCategory.CLASS_D_AMPLIFIER,
                ComponentCategory.AUDIO_CODEC,
                ComponentCategory.DSP_PROCESSOR,
            }
        ):
            return ("audio", "speaker_output_channels")
        return {
            "sample_rate": ("audio", "sample_rate"),
            "bit_depth": ("audio", "bit_depth"),
            "speaker_load": ("electrical", "speaker_impedance"),
            "output_power": ("electrical", "speaker_power_per_channel"),
            "input_voltage_range": ("power", "input_supply_voltage"),
        }.get(fact)

    @staticmethod
    def _resolved_value(
        category: ComponentCategory,
        fact: str,
        requirement: Requirement | None,
        spec: MasterSpec,
    ) -> tuple[RequirementStatus, JsonValue | None, str | None, bool]:
        if requirement is not None:
            return requirement.status, requirement.value, requirement.unit, requirement.critical
        if category is ComponentCategory.DSP_PROCESSOR and fact == "compute_throughput":
            fxlms = spec.processing.requirements.get("fxlms_support")
            if fxlms and fxlms.status is RequirementStatus.RESOLVED and fxlms.value is True:
                return RequirementStatus.UNKNOWN, None, None, True
        return RequirementStatus.UNKNOWN, None, None, fact in _HARD_FACTS
