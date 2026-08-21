from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    VerificationReport,
)


class Validator(Protocol):
    @property
    def name(self) -> str: ...

    def validate(self, state: DesignState) -> Sequence[ValidationResult]: ...


class ValidationEngine:
    def __init__(self, validators: Sequence[Validator]) -> None:
        self.validators = tuple(validators)

    def run(self, state: DesignState, *, report_id: str, stage: str) -> VerificationReport:
        results = [result for validator in self.validators for result in validator.validate(state)]
        if not results:
            results = [
                ValidationResult(
                    result_id="validation-unavailable",
                    validator="validation_engine",
                    status=ValidationStatus.UNKNOWN,
                    severity=ValidationSeverity.CRITICAL,
                    summary="No validation results were produced",
                    details=["An empty validator set or empty validator output cannot pass."],
                )
            ]
        return VerificationReport(
            report_id=report_id,
            stage=stage,
            results=results,
            can_advance=not any(result.blocks_progression for result in results),
        )
