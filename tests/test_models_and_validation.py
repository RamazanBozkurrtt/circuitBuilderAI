from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_pcb.models.spec import MasterSpec, Requirement, RequirementStatus
from ai_pcb.models.state import DesignState, WorkflowStage
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    VerificationReport,
)
from ai_pcb.validation.engine import ValidationEngine
from ai_pcb.validation.spec import MasterSpecValidator
from ai_pcb.workflow.transitions import InvalidStateTransition, transition_state


def test_malformed_engineering_state_is_rejected(resolved_spec: MasterSpec) -> None:
    with pytest.raises(ValidationError):
        DesignState.model_validate(
            {
                "project_name": "test-project",
                "master_spec": resolved_spec.model_dump(),
                "iteration": -1,
                "unexpected": "must fail closed",
            }
        )


def test_unknown_requirement_cannot_contain_value() -> None:
    with pytest.raises(ValidationError, match="UNKNOWN requirements cannot contain a value"):
        Requirement(
            status=RequirementStatus.UNKNOWN,
            critical=True,
            value=5,
            description="Contradictory requirement",
        )


def test_critical_missing_requirements_block_progression() -> None:
    spec = MasterSpec.empty_template("empty-project")
    state = DesignState(project_name="empty-project", master_spec=spec)
    report = ValidationEngine([MasterSpecValidator()]).run(
        state, report_id="empty-spec", stage="SPECIFICATION"
    )
    assert not report.can_advance
    assert all(result.status is ValidationStatus.UNKNOWN for result in report.results)
    assert all(result.severity is ValidationSeverity.CRITICAL for result in report.results)


def test_critical_unknown_is_not_pass() -> None:
    result = ValidationResult(
        result_id="unknown-critical",
        validator="test",
        status=ValidationStatus.UNKNOWN,
        severity=ValidationSeverity.CRITICAL,
        summary="Cannot be verified",
    )
    assert result.status is not ValidationStatus.PASS
    assert result.blocks_progression


def test_warning_remains_warning_and_does_not_block() -> None:
    warning = ValidationResult(
        result_id="warning",
        validator="test",
        status=ValidationStatus.WARNING,
        severity=ValidationSeverity.HIGH,
        summary="Review requested",
    )
    report = VerificationReport(
        report_id="warning-report", stage="SPECIFICATION", results=[warning], can_advance=True
    )
    assert report.results[0].status is ValidationStatus.WARNING
    assert report.can_advance


def test_empty_validation_engine_fails_closed(design_state: DesignState) -> None:
    report = ValidationEngine([]).run(
        design_state, report_id="no-validators", stage="SPECIFICATION"
    )
    assert not report.can_advance
    assert report.results[0].status is ValidationStatus.UNKNOWN
    assert report.results[0].severity is ValidationSeverity.CRITICAL


def test_failed_verification_cannot_advance_stage(design_state: DesignState) -> None:
    failure = ValidationResult(
        result_id="failure",
        validator="test",
        status=ValidationStatus.FAIL,
        severity=ValidationSeverity.CRITICAL,
        summary="Failed",
    )
    report = VerificationReport(
        report_id="failed-report",
        stage="SPECIFICATION",
        results=[failure],
        can_advance=False,
    )
    state = design_state.model_copy(update={"verification_reports": [report]})
    with pytest.raises(InvalidStateTransition, match="failed verification"):
        transition_state(state, WorkflowStage.ARCHITECTURE, "should be blocked")
