from __future__ import annotations

from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)


class EvidenceReferenceValidator:
    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.store = evidence_store

    @property
    def name(self) -> str:
        return "evidence_references"

    def validate(self, state: DesignState) -> list[ValidationResult]:
        referenced = set(state.evidence_ids)
        for section in state.master_spec.sections().values():
            for requirement in section.requirements.values():
                referenced.update(requirement.evidence_ids)
        for decision in state.decisions:
            referenced.update(decision.evidence_ids)
        for report in state.verification_reports:
            for result in report.results:
                referenced.update(result.evidence_ids)
        missing = sorted(item for item in referenced if not self.store.contains(item))
        return [
            ValidationResult(
                result_id="evidence-references",
                validator=self.name,
                status=ValidationStatus.FAIL if missing else ValidationStatus.PASS,
                severity=ValidationSeverity.CRITICAL if missing else ValidationSeverity.INFO,
                summary=(
                    f"Unknown evidence references: {', '.join(missing)}"
                    if missing
                    else "All evidence references resolve"
                ),
                details=missing,
            )
        ]


class EvidenceValidationUnavailable:
    """Blocks referenced evidence when a workflow caller omitted its evidence store."""

    @property
    def name(self) -> str:
        return "evidence_references"

    def validate(self, state: DesignState) -> list[ValidationResult]:
        referenced = set(state.evidence_ids)
        for section in state.master_spec.sections().values():
            for requirement in section.requirements.values():
                referenced.update(requirement.evidence_ids)
        for decision in state.decisions:
            referenced.update(decision.evidence_ids)
        if referenced:
            return [
                ValidationResult(
                    result_id="evidence-store-unavailable",
                    validator=self.name,
                    status=ValidationStatus.UNKNOWN,
                    severity=ValidationSeverity.CRITICAL,
                    summary="Evidence references cannot be resolved without an evidence store",
                    details=sorted(referenced),
                )
            ]
        return [
            ValidationResult(
                result_id="evidence-not-referenced",
                validator=self.name,
                status=ValidationStatus.NOT_APPLICABLE,
                severity=ValidationSeverity.INFO,
                summary="The current state contains no evidence references",
            )
        ]
