from __future__ import annotations

from ai_pcb.models.state import DesignState, WorkflowStage
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    VerificationReport,
)
from ai_pcb.workflow.graph import Phase1Workflow


def report_for(stage: str, status: ValidationStatus) -> VerificationReport:
    severity = (
        ValidationSeverity.INFO
        if status is ValidationStatus.PASS
        else ValidationSeverity.CRITICAL
    )
    result = ValidationResult(
        result_id=f"{stage}-{status.value.lower()}",
        validator="test_handler",
        status=status,
        severity=severity,
        summary=f"{stage}: {status}",
    )
    return VerificationReport(
        report_id=f"{stage}-{status.value.lower()}",
        stage=stage,
        results=[result],
        can_advance=status is ValidationStatus.PASS,
    )


def test_phase1_placeholder_is_unknown_and_blocks(design_state: DesignState) -> None:
    final = Phase1Workflow(max_iterations=3).invoke(design_state)
    assert final.workflow_stage is WorkflowStage.BLOCKED
    unavailable = final.verification_reports[-1].results[0]
    assert unavailable.status is ValidationStatus.UNKNOWN
    assert unavailable.severity is ValidationSeverity.CRITICAL
    assert "unavailable" in unavailable.summary


def test_workflow_checkpoints_major_state_changes(design_state: DesignState) -> None:
    checkpoints: list[DesignState] = []
    final = Phase1Workflow(
        max_iterations=3, checkpoint=lambda state: checkpoints.append(state.model_copy(deep=True))
    ).invoke(design_state)
    assert checkpoints
    assert checkpoints[-1] == final
    assert any(state.verification_reports for state in checkpoints)


def test_workflow_iterations_are_bounded(design_state: DesignState) -> None:
    handlers = {
        name: (lambda state, stage=name: report_for(stage, ValidationStatus.PASS))
        for name in (
            "architecture",
            "component_selection",
            "datasheet_analysis",
            "schematic_design",
            "pcb_layout",
            "pcb_validation",
            "manufacturing",
            "final_review",
        )
    }
    handlers["schematic_validation"] = lambda state: report_for(
        "schematic_validation", ValidationStatus.FAIL
    )
    final = Phase1Workflow(max_iterations=2, stage_handlers=handlers).invoke(design_state)
    assert final.workflow_stage is WorkflowStage.BLOCKED
    assert final.iteration == 2
    assert any("maximum design iterations" in blocker for blocker in final.blockers)
