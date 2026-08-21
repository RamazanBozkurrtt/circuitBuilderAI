from __future__ import annotations

from ai_pcb.models.spec import RequirementStatus
from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)


class MasterSpecValidator:
    """Structural and explicit-unknown checks only; no electrical claims are made."""

    @property
    def name(self) -> str:
        return "master_spec"

    def validate(self, state: DesignState) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        for section_name, section in state.master_spec.sections().items():
            if not section.requirements:
                results.append(
                    ValidationResult(
                        result_id=f"spec-{section_name}-empty",
                        validator=self.name,
                        status=ValidationStatus.UNKNOWN,
                        severity=ValidationSeverity.CRITICAL,
                        summary=f"{section_name} has no declared requirements",
                        details=["The user must explicitly resolve applicability and values."],
                    )
                )
                continue
            for requirement_name, requirement in section.requirements.items():
                if requirement.status is RequirementStatus.UNKNOWN:
                    results.append(
                        ValidationResult(
                            result_id=f"spec-{section_name}-{requirement_name}",
                            validator=self.name,
                            status=ValidationStatus.UNKNOWN,
                            severity=(
                                ValidationSeverity.CRITICAL
                                if requirement.critical
                                else ValidationSeverity.MEDIUM
                            ),
                            summary=f"Requirement is unresolved: {section_name}.{requirement_name}",
                        )
                    )
        if not results:
            results.append(
                ValidationResult(
                    result_id="spec-contract-complete",
                    validator=self.name,
                    status=ValidationStatus.PASS,
                    severity=ValidationSeverity.INFO,
                    summary="All declared MASTER_SPEC requirements are resolved",
                )
            )
        return results

