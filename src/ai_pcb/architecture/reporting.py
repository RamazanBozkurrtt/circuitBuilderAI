from __future__ import annotations

from ai_pcb.models.state import DesignState


def render_phase3_report(state: DesignState) -> str:
    resolved = " -> ".join(item.id for item in state.resolved_specializations)
    lines = [
        f"Phase 3 architecture/component report: {state.project_name}",
        f"Resolved specializations: {resolved}",
        f"Phase 3 complete: {'yes' if state.phase3_complete else 'no'}",
    ]
    if state.architecture is not None:
        lines.extend(
            [
                f"Provisional architecture: {state.architecture.name}",
                "Functional blocks:",
                *[
                    f"  - {block.name}: "
                    f"{', '.join(block.required_capabilities) or 'no capabilities recorded'}"
                    for block in state.architecture.functional_blocks
                ],
            ]
        )
    if state.architecture_decision is not None:
        lines.append(
            "Viable architecture alternatives: "
            + (", ".join(state.architecture_decision.viable_alternative_ids) or "none")
        )
    lines.append("Major component plan:")
    candidate_by_id = {item.candidate_id: item for item in state.component_candidates}
    evaluation_by_id = {item.candidate_id: item for item in state.component_evaluations}
    for selection in state.components:
        selected = (
            candidate_by_id[selection.selected_candidate_id].part_number
            if selection.selected_candidate_id in candidate_by_id
            else "no evidenced selection"
        )
        alternatives = [
            candidate_by_id[item].part_number
            for item in selection.viable_alternative_ids
            if item in candidate_by_id
        ]
        lines.append(
            f"  - {selection.category.value}: {selected}; lifecycle={selection.status.value}; "
            f"alternatives: {', '.join(alternatives) or 'none evidenced'}"
        )
        lines.extend(f"      blocker: {item}" for item in selection.unresolved_trade_offs)
    lines.append("Evidence-backed component candidates:")
    for candidate in state.component_candidates:
        evaluation = evaluation_by_id.get(candidate.candidate_id)
        lines.append(
            f"  - {candidate.category.value} | {candidate.manufacturer} "
            f"{candidate.part_number} | evidence={candidate.evidence_status.value} | "
            f"viability={evaluation.viability.value if evaluation else 'NOT_EVALUATED'}"
        )
        for fact in candidate.facts:
            value = fact.value.value if fact.value.value is not None else "UNKNOWN"
            lines.append(
                f"      {fact.attribute}: {value} {fact.value.unit or ''} "
                f"[{', '.join(fact.value.evidence_ids)}]"
            )
        if evaluation is not None:
            lines.extend(f"      rejected: {item}" for item in evaluation.rejection_reasons)
            lines.extend(f"      unresolved: {item}" for item in evaluation.unresolved_trade_offs)
    lines.append("Evidence acquisition requirements:")
    lines.extend(
        f"  - {item.category.value}: {', '.join(item.required_facts)}"
        for item in state.evidence_acquisition_requirements
    )
    if not state.evidence_acquisition_requirements:
        lines.append("  - none")
    unresolved = [
        requirement.requirement_id
        for requirement in state.component_requirements
        if requirement.status.value == "UNKNOWN"
    ]
    lines.append("Unresolved component variables: " + (", ".join(unresolved) or "none"))
    if state.computational_budget is not None:
        lines.append(f"DSP/FxLMS suitability: {state.computational_budget.suitability.value}")
        lines.append(f"  {state.computational_budget.rationale}")
        for scenario in state.computational_budget.scenarios:
            lines.append(f"  - {scenario.label}; DESIGN_EXPLORATION={scenario.design_exploration}")
            lines.extend(f"      assumption: {item}" for item in scenario.assumptions)
            lines.extend(
                f"      operations: {item}" for item in scenario.operations_per_second.conditions
            )
            lines.append(
                f"      budget: {scenario.operations_per_second.value} "
                f"{scenario.operations_per_second.unit}; memory={scenario.memory_required.value} "
                f"{scenario.memory_required.unit}; "
                f"headroom={scenario.processing_headroom.status.value}"
            )
    if state.latency_budget is not None:
        lines.append(f"Latency total: {state.latency_budget.total.status.value}")
        for contribution in state.latency_budget.contributions:
            lines.append(
                f"  - {contribution.contributor.value}: {contribution.latency.status.value}"
            )
            lines.extend(f"      {condition}" for condition in contribution.latency.conditions)
        for comparison in state.latency_budget.candidate_comparisons:
            latency_value = comparison.documented_converter_delay
            lines.append(
                f"  - comparison {comparison.comparison_id}: {latency_value.status.value} "
                f"{latency_value.value if latency_value.value is not None else ''} "
                f"{latency_value.unit or ''}".rstrip()
            )
    if state.design_variables:
        lines.append("Design-variable closure:")
        for variable in state.design_variables:
            design_value = (
                variable.resolution.value
                if variable.resolution is not None
                else "scenario envelope"
                if variable.envelope is not None
                else "UNKNOWN"
            )
            lines.append(
                f"  - {variable.variable_id}: {variable.kind.value} / "
                f"{variable.status.value} / {design_value}"
            )
    if state.phase4_readiness is not None:
        lines.append(f"Phase 4 readiness: {state.phase4_readiness.status.value}")
        lines.extend(f"  - blocker: {item}" for item in state.phase4_readiness.blockers)
    if state.microphone_front_end is not None:
        lines.append(
            "Microphone front end: "
            f"{state.microphone_front_end.selected_technology} -> "
            f"{state.microphone_front_end.adc_part_number}"
        )
        lines.extend(
            f"  - unresolved: {item}" for item in state.microphone_front_end.unresolved_terms
        )
    if state.clock_tree is not None:
        lines.append(f"Clock tree master: {state.clock_tree.audio_master}")
        lines.extend(
            f"  - {signal.signal_id}: {signal.frequency_hz} Hz; {signal.divider}"
            for signal in state.clock_tree.signals
        )
    if state.power_tree is not None:
        lines.append(f"Power tree: {state.power_tree.tree_id}")
        lines.extend(
            f"  - {rail.rail_id}: {rail.nominal_voltage.value} "
            f"{rail.nominal_voltage.unit}; source={rail.source}"
            for rail in state.power_tree.rails
        )
        lines.append(
            f"  - known documented subtotal: {state.power_tree.known_minimum_power.value} "
            f"{state.power_tree.known_minimum_power.unit}"
        )
    lines.append("Risks:")
    if state.architecture is not None:
        lines.extend(f"  - {risk.description}" for risk in state.architecture.risks)
    return "\n".join(lines) + "\n"
