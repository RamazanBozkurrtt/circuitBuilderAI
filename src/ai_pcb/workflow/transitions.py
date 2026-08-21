from __future__ import annotations

from ai_pcb.models.state import DesignState, StateTransition, WorkflowStage


class InvalidStateTransition(ValueError):
    pass


_NEXT: dict[WorkflowStage, frozenset[WorkflowStage]] = {
    WorkflowStage.SPECIFICATION: frozenset({WorkflowStage.ARCHITECTURE, WorkflowStage.BLOCKED}),
    WorkflowStage.ARCHITECTURE: frozenset(
        {WorkflowStage.COMPONENT_SELECTION, WorkflowStage.BLOCKED}
    ),
    WorkflowStage.COMPONENT_SELECTION: frozenset(
        {
            WorkflowStage.ARCHITECTURE,
            WorkflowStage.DATASHEET_ANALYSIS,
            WorkflowStage.BLOCKED,
        }
    ),
    WorkflowStage.DATASHEET_ANALYSIS: frozenset({WorkflowStage.SCHEMATIC, WorkflowStage.BLOCKED}),
    WorkflowStage.SCHEMATIC: frozenset(
        {WorkflowStage.SCHEMATIC_VERIFICATION, WorkflowStage.BLOCKED}
    ),
    WorkflowStage.SCHEMATIC_VERIFICATION: frozenset(
        {WorkflowStage.SCHEMATIC, WorkflowStage.PCB_LAYOUT, WorkflowStage.BLOCKED}
    ),
    WorkflowStage.PCB_LAYOUT: frozenset({WorkflowStage.PCB_VERIFICATION, WorkflowStage.BLOCKED}),
    WorkflowStage.PCB_VERIFICATION: frozenset(
        {WorkflowStage.PCB_LAYOUT, WorkflowStage.MANUFACTURING, WorkflowStage.BLOCKED}
    ),
    WorkflowStage.MANUFACTURING: frozenset({WorkflowStage.COMPLETE, WorkflowStage.BLOCKED}),
    WorkflowStage.COMPLETE: frozenset(),
    WorkflowStage.BLOCKED: frozenset({WorkflowStage.SPECIFICATION}),
}


def transition_state(
    state: DesignState,
    target: WorkflowStage,
    reason: str,
    *,
    require_verification: bool = True,
) -> DesignState:
    if target not in _NEXT[state.workflow_stage]:
        raise InvalidStateTransition(f"cannot transition {state.workflow_stage} to {target}")
    if (
        require_verification
        and target is not WorkflowStage.BLOCKED
        and state.verification_reports
        and not state.verification_reports[-1].can_advance
    ):
        raise InvalidStateTransition("failed verification blocks stage advancement")
    transition = StateTransition(
        from_stage=state.workflow_stage,
        to_stage=target,
        reason=reason,
        iteration=state.iteration,
    )
    return state.model_copy(
        update={"workflow_stage": target, "history": [*state.history, transition]}
    )
