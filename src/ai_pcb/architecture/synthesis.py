from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise

from ai_pcb.models.architecture import (
    ArchitectureCandidate,
    ArchitectureConnection,
    ArchitectureCriterionEvaluation,
    ArchitectureEvaluation,
    ArchitectureRisk,
    BlockInterface,
    ConstraintKind,
    DerivedConstraint,
    EngineeringValue,
    FunctionalBlock,
    InterfaceDirection,
    SystemArchitecture,
    ValueStatus,
)
from ai_pcb.models.spec import MasterSpec, Requirement, RequirementStatus
from ai_pcb.models.validation import ValidationSeverity, ValidationStatus
from ai_pcb.specializations.models import ResolvedSpecializationContext

_TOPOLOGIES = (
    ("separate_converters", "Separate ADC + DSP + DAC"),
    ("multichannel_codec", "Multichannel codec + DSP"),
    ("integrated_converters", "DSP with integrated converters"),
)


def _requirement(spec: MasterSpec, section: str, name: str) -> Requirement | None:
    return spec.sections()[section].requirements.get(name)


def _value(requirement: Requirement | None) -> EngineeringValue:
    if requirement is None or requirement.status is RequirementStatus.UNKNOWN:
        return EngineeringValue(status=ValueStatus.UNKNOWN)
    return EngineeringValue(
        status=ValueStatus.KNOWN,
        value=requirement.value,
        unit=requirement.unit,
        evidence_ids=requirement.evidence_ids,
        conditions=["Derived directly from MASTER_SPEC."],
    )


def _constraint(
    spec: MasterSpec,
    section: str,
    name: str,
    *,
    kind: ConstraintKind,
    description: str,
) -> DerivedConstraint:
    requirement = _requirement(spec, section, name)
    if requirement is None:
        return DerivedConstraint(
            constraint_id=f"{section}.{name}",
            description=description,
            kind=kind,
            status=RequirementStatus.UNKNOWN,
            critical=False,
            source_requirements=[f"{section}.{name}"],
        )
    return DerivedConstraint(
        constraint_id=f"{section}.{name}",
        description=description,
        kind=kind,
        status=requirement.status,
        value=requirement.value,
        unit=requirement.unit,
        critical=requirement.critical,
        source_requirements=[f"{section}.{name}"],
    )


class ArchitectureSynthesizer:
    """Deterministically builds alternatives from the spec and resolved declarative context."""

    def synthesize(
        self,
        spec: MasterSpec,
        context: ResolvedSpecializationContext,
        *,
        attempt: int = 1,
        correction_notes: Iterable[str] = (),
    ) -> list[ArchitectureCandidate]:
        roles = [item.role for item in context.architecture_blocks]
        has_audio_conversion = "audio_conversion" in roles
        topologies = _TOPOLOGIES if has_audio_conversion else (("guided", "Guided topology"),)
        candidates: list[ArchitectureCandidate] = []
        for topology, label in topologies:
            architecture = self._build_architecture(
                spec,
                context,
                topology=topology,
                label=label,
                attempt=attempt,
                correction_notes=list(correction_notes),
            )
            candidates.append(
                ArchitectureCandidate(
                    candidate_id=f"architecture-{topology}-a{attempt}",
                    architecture=architecture,
                    rationale=(
                        f"{label} preserves a distinct converter/processor integration trade-off "
                        "for evidence-grounded comparison."
                    ),
                    evaluation=self._evaluate(architecture, attempt),
                )
            )
        return candidates

    def _build_architecture(
        self,
        spec: MasterSpec,
        context: ResolvedSpecializationContext,
        *,
        topology: str,
        label: str,
        attempt: int,
        correction_notes: list[str],
    ) -> SystemArchitecture:
        input_channels = _requirement(spec, "audio", "microphone_input_channels")
        output_channels = _requirement(spec, "audio", "speaker_output_channels")
        guided_roles = [item.role for item in context.architecture_blocks]
        if topology == "separate_converters":
            roles = [role for role in guided_roles if role != "audio_conversion"]
            insert_at = roles.index("dsp_processor") if "dsp_processor" in roles else len(roles)
            roles[insert_at:insert_at] = ["adc"]
            dsp_index = roles.index("dsp_processor") + 1 if "dsp_processor" in roles else len(roles)
            roles[dsp_index:dsp_index] = ["dac"]
        elif topology == "multichannel_codec":
            roles = ["audio_codec" if role == "audio_conversion" else role for role in guided_roles]
        elif topology == "integrated_converters":
            roles = [role for role in guided_roles if role != "audio_conversion"]
        else:
            roles = guided_roles

        blocks = [
            self._block(
                role,
                context,
                input_channels=input_channels,
                output_channels=output_channels,
                integrated=topology == "integrated_converters" and role == "dsp_processor",
            )
            for role in dict.fromkeys(roles)
        ]
        signal_roles = [
            role
            for role in (
                "microphone_front_end",
                "adc",
                "audio_codec",
                "dsp_processor",
                "dac",
                "output_amplification",
            )
            if any(block.role == role for block in blocks)
        ]
        if topology == "integrated_converters":
            signal_roles = [
                role for role in signal_roles if role not in {"adc", "dac", "audio_codec"}
            ]
        connections = [
            ArchitectureConnection(
                connection_id=f"{left}-to-{right}",
                source_block_id=left,
                destination_block_id=right,
                interface_type=(
                    "analog_audio"
                    if left in {"microphone_front_end", "dac"}
                    else "synchronous_digital_audio"
                ),
                latency_critical=True,
                synchronization_required=True,
            )
            for left, right in pairwise(signal_roles)
        ]
        hard_constraints = [
            _constraint(
                spec,
                "audio",
                "microphone_input_channels",
                kind=ConstraintKind.HARD_CONSTRAINT,
                description="Required microphone input channels",
            ),
            _constraint(
                spec,
                "audio",
                "speaker_output_channels",
                kind=ConstraintKind.HARD_CONSTRAINT,
                description="Required speaker output channels",
            ),
            _constraint(
                spec,
                "audio",
                "onboard_class_d_amplification",
                kind=ConstraintKind.HARD_CONSTRAINT,
                description="Onboard Class-D amplification",
            ),
            _constraint(
                spec,
                "processing",
                "fxlms_support",
                kind=ConstraintKind.HARD_CONSTRAINT,
                description="FxLMS algorithm support",
            ),
            _constraint(
                spec,
                "processing",
                "dedicated_dsp_required",
                kind=ConstraintKind.HARD_CONSTRAINT,
                description="Dedicated DSP processing",
            ),
        ]
        objectives = [
            _constraint(
                spec,
                "design_constraints",
                name,
                kind=ConstraintKind.OPTIMIZATION_OBJECTIVE,
                description=description,
            )
            for name, description in (
                ("minimize_end_to_end_latency", "Minimize end-to-end ANC latency"),
                ("maximize_dsp_headroom", "Maximize real-time FxLMS DSP headroom"),
                ("minimize_noise_coupling", "Minimize analog/digital/power noise coupling"),
                ("optimize_converter_signal_path", "Optimize ADC to DSP to DAC signal path"),
            )
        ]
        unresolved = [
            _constraint(
                spec,
                section,
                name,
                kind=ConstraintKind.HARD_CONSTRAINT,
                description=description,
            )
            for section, name, description in (
                ("audio", "sample_rate", "Audio sample rate design variable"),
                ("audio", "bit_depth", "Audio bit depth design variable"),
                ("audio", "speaker_impedance", "Speaker load design variable"),
                ("power", "input_supply_voltage", "Input supply voltage design variable"),
            )
            if (_requirement(spec, section, name) is None)
            or (_requirement(spec, section, name).status is RequirementStatus.UNKNOWN)  # type: ignore[union-attr]
        ]
        risks = [
            ArchitectureRisk(
                risk_id=f"{topology}-latency-evidence",
                description=(
                    "Converter, buffering, DSP, and output-path latency remain unevidenced."
                ),
                severity=ValidationSeverity.CRITICAL,
                affected_blocks=[block.block_id for block in blocks if block.role in signal_roles],
                mitigation=(
                    "Acquire manufacturer latency data and close a condition-specific budget."
                ),
            ),
            ArchitectureRisk(
                risk_id=f"{topology}-compute-evidence",
                description="Audio I/O capacity alone cannot establish FxLMS compute suitability.",
                severity=ValidationSeverity.CRITICAL,
                affected_blocks=["dsp_processor"] if "dsp_processor" in roles else [],
                mitigation="Define processing scenarios and acquire compute and memory evidence.",
            ),
        ]
        if correction_notes:
            risks.append(
                ArchitectureRisk(
                    risk_id=f"{topology}-review-a{attempt}",
                    description="; ".join(correction_notes),
                    severity=ValidationSeverity.HIGH,
                    mitigation="This proposal records the prior independent-review correction.",
                )
            )
        return SystemArchitecture(
            architecture_id=f"system-{topology}-a{attempt}",
            name=label,
            topology=topology,
            functional_blocks=blocks,
            connections=connections,
            hard_constraints=hard_constraints,
            optimization_objectives=objectives,
            risks=risks,
            unresolved_requirements=unresolved,
        )

    @staticmethod
    def _block(
        role: str,
        context: ResolvedSpecializationContext,
        *,
        input_channels: Requirement | None,
        output_channels: Requirement | None,
        integrated: bool,
    ) -> FunctionalBlock:
        guidance = next((item for item in context.architecture_blocks if item.role == role), None)
        channels: list[DerivedConstraint] = []
        interfaces: list[BlockInterface] = []
        if role in {"microphone_front_end", "adc", "audio_codec", "dsp_processor"}:
            channels.append(
                DerivedConstraint(
                    constraint_id=f"{role}.input_channels",
                    description="Required synchronized audio input capacity",
                    kind=ConstraintKind.HARD_CONSTRAINT,
                    status=(input_channels.status if input_channels else RequirementStatus.UNKNOWN),
                    value=input_channels.value if input_channels else None,
                    critical=True,
                    source_requirements=["audio.microphone_input_channels"],
                )
            )
            interfaces.append(
                BlockInterface(
                    interface_id=f"{role}-audio-in",
                    name="Audio input",
                    direction=InterfaceDirection.INPUT,
                    interface_type="audio",
                    channels=_value(input_channels),
                )
            )
        if role in {"audio_codec", "dsp_processor", "dac", "output_amplification"}:
            channels.append(
                DerivedConstraint(
                    constraint_id=f"{role}.output_channels",
                    description="Required synchronized audio output capacity",
                    kind=ConstraintKind.HARD_CONSTRAINT,
                    status=(
                        output_channels.status if output_channels else RequirementStatus.UNKNOWN
                    ),
                    value=output_channels.value if output_channels else None,
                    critical=True,
                    source_requirements=["audio.speaker_output_channels"],
                )
            )
            interfaces.append(
                BlockInterface(
                    interface_id=f"{role}-audio-out",
                    name="Audio output",
                    direction=InterfaceDirection.OUTPUT,
                    interface_type="audio",
                    channels=_value(output_channels),
                )
            )
        capabilities = (
            list(guidance.required_capabilities)
            if guidance is not None
            else ["evidenced synchronized multichannel conversion"]
        )
        assumptions = []
        if integrated:
            capabilities.append("integrated four-channel ADC and DAC capability")
            assumptions.append(
                "Integrated converters are a topology exploration, not a user requirement."
            )
        return FunctionalBlock(
            block_id=role,
            role=role,
            name=role.replace("_", " ").title(),
            required_capabilities=capabilities,
            channel_requirements=channels,
            interfaces=interfaces,
            assumptions=assumptions,
        )

    @staticmethod
    def _evaluate(architecture: SystemArchitecture, attempt: int) -> ArchitectureEvaluation:
        roles = {block.role for block in architecture.functional_blocks}
        criteria: list[ArchitectureCriterionEvaluation] = []
        for constraint in architecture.hard_constraints:
            status = ValidationStatus.PASS
            if constraint.status is RequirementStatus.UNKNOWN:
                status = ValidationStatus.UNKNOWN
            elif constraint.constraint_id.endswith("onboard_class_d_amplification"):
                if constraint.value is True and "output_amplification" not in roles:
                    status = ValidationStatus.FAIL
            elif (
                constraint.constraint_id.endswith("dedicated_dsp_required")
                and constraint.value is True
                and "dsp_processor" not in roles
            ):
                status = ValidationStatus.FAIL
            criteria.append(
                ArchitectureCriterionEvaluation(
                    criterion_id=f"architecture-{constraint.constraint_id}",
                    kind=ConstraintKind.HARD_CONSTRAINT,
                    status=status,
                    rationale=constraint.description,
                )
            )
        return ArchitectureEvaluation(
            evaluation_id=f"evaluation-{architecture.topology}-a{attempt}",
            criteria=criteria,
            viable=not any(item.status is ValidationStatus.FAIL for item in criteria),
            unresolved_trade_offs=[
                "Latency cannot be ranked until condition-specific evidence is acquired.",
                (
                    "Converter integration trades routing simplicity against choice and "
                    "evidence depth."
                ),
            ],
        )
