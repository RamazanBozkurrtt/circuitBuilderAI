from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    ValidatorApplicability,
    VerificationReport,
)
from ai_pcb.specializations.capabilities import current_engine_capabilities
from ai_pcb.specializations.models import EngineeringCapability


class Validator(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def applicability(self) -> ValidatorApplicability: ...

    def validate(self, state: DesignState) -> Sequence[ValidationResult]: ...


class ValidationEngine:
    def __init__(
        self,
        validators: Sequence[Validator],
        *,
        available_capabilities: frozenset[EngineeringCapability] | None = None,
    ) -> None:
        self.validators = tuple(validators)
        self.available_capabilities = (
            current_engine_capabilities()
            if available_capabilities is None
            else available_capabilities
        )

    def run(self, state: DesignState, *, report_id: str, stage: str) -> VerificationReport:
        active = set(state.specialization_context().resolved_ids)
        results: list[ValidationResult] = []
        for validator in self.validators:
            applicability = validator.applicability
            if applicability.applicable_stages and stage not in applicability.applicable_stages:
                continue
            if applicability.applicable_specializations and active.isdisjoint(
                applicability.applicable_specializations
            ):
                continue
            capability = applicability.required_capability
            if capability is not None and capability not in self.available_capabilities:
                results.append(
                    ValidationResult(
                        result_id=f"{validator.name}-capability-unavailable",
                        validator=validator.name,
                        status=ValidationStatus.UNKNOWN,
                        severity=ValidationSeverity.CRITICAL,
                        summary=f"Required validator capability is unavailable: {capability.value}",
                        details=["Unavailable validation can never produce PASS."],
                    )
                )
                continue
            results.extend(validator.validate(state))
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
