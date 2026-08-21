from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_pcb.decisions.lifecycle import DecisionLifecycle, InvalidDecisionTransition
from ai_pcb.evidence.store import EvidenceNotFoundError, EvidenceStore
from ai_pcb.models.decision import DecisionStatus, EngineeringDecision
from ai_pcb.models.evidence import Evidence, EvidenceProvenance, EvidenceSource
from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)
from ai_pcb.validation.engine import ValidationEngine
from ai_pcb.validation.references import EvidenceReferenceValidator


def evidence_item() -> Evidence:
    return Evidence(
        evidence_id="user-spec-1",
        title="Explicit user requirement",
        provenance=EvidenceProvenance(source=EvidenceSource.USER_SPEC, section="test"),
        extracted_content="A user supplied this test fact.",
        normalized_fact="Test fact is explicitly supplied.",
        confidence=1.0,
    )


def test_invalid_evidence_references_are_detected(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    with pytest.raises(EvidenceNotFoundError, match="missing-id"):
        store.require_all(["missing-id"])


def test_invalid_evidence_references_fail_validation(
    tmp_path: Path, design_state: DesignState
) -> None:
    state = design_state.model_copy(update={"evidence_ids": ["missing-id"]})
    store = EvidenceStore(tmp_path / "evidence")
    report = ValidationEngine([EvidenceReferenceValidator(store)]).run(
        state, report_id="evidence-check", stage="SPECIFICATION"
    )
    assert not report.can_advance
    assert report.results[0].status is ValidationStatus.FAIL


def test_evidence_round_trip(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    evidence = evidence_item()
    store.add(evidence)
    assert store.get(evidence.evidence_id) == evidence


def test_validated_decision_model_requires_support() -> None:
    with pytest.raises(ValidationError, match="require evidence"):
        EngineeringDecision(
            decision_id="decision-1",
            title="Unsupported",
            statement="Must not validate",
            status=DecisionStatus.VALIDATED,
        )


def test_decision_lifecycle_requires_passing_validation(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    store.add(evidence_item())
    lifecycle = DecisionLifecycle(store)
    proposed = EngineeringDecision(
        decision_id="decision-1",
        title="Test choice",
        statement="Select the test option",
        evidence_ids=["user-spec-1"],
        validation_result_ids=["validation-1"],
        alternatives=[],
        assumptions=["Test assumption retained"],
        risks=["Test risk retained"],
    )
    verified = lifecycle.transition(
        proposed, DecisionStatus.EVIDENCE_VERIFIED, "Evidence resolved"
    )
    unknown = ValidationResult(
        result_id="validation-1",
        validator="test",
        status=ValidationStatus.UNKNOWN,
        severity=ValidationSeverity.CRITICAL,
        summary="Not deterministically verified",
    )
    with pytest.raises(InvalidDecisionTransition, match="PASS"):
        lifecycle.transition(
            verified,
            DecisionStatus.VALIDATED,
            "Must fail",
            validation_results=[unknown],
        )

    passed = unknown.model_copy(
        update={"status": ValidationStatus.PASS, "severity": ValidationSeverity.INFO}
    )
    validated = lifecycle.transition(
        verified,
        DecisionStatus.VALIDATED,
        "Deterministic validation passed",
        validation_results=[passed],
    )
    assert validated.status is DecisionStatus.VALIDATED
    assert validated.assumptions == proposed.assumptions
    assert validated.risks == proposed.risks
