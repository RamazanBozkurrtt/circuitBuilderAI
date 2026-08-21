from __future__ import annotations

from collections.abc import Collection

from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.decision import (
    DecisionStatus,
    DecisionTransition,
    EngineeringDecision,
)
from ai_pcb.models.validation import ValidationResult, ValidationStatus


class InvalidDecisionTransition(ValueError):
    pass


_ALLOWED: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.PROPOSED: frozenset(
        {DecisionStatus.EVIDENCE_VERIFIED, DecisionStatus.REJECTED, DecisionStatus.SUPERSEDED}
    ),
    DecisionStatus.EVIDENCE_VERIFIED: frozenset(
        {DecisionStatus.VALIDATED, DecisionStatus.REJECTED, DecisionStatus.SUPERSEDED}
    ),
    DecisionStatus.VALIDATED: frozenset({DecisionStatus.SUPERSEDED}),
    DecisionStatus.REJECTED: frozenset(),
    DecisionStatus.SUPERSEDED: frozenset(),
}


class DecisionLifecycle:
    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.evidence_store = evidence_store

    def transition(
        self,
        decision: EngineeringDecision,
        target: DecisionStatus,
        reason: str,
        validation_results: Collection[ValidationResult] = (),
    ) -> EngineeringDecision:
        if target not in _ALLOWED[decision.status]:
            raise InvalidDecisionTransition(f"cannot transition {decision.status} to {target}")

        if target in {DecisionStatus.EVIDENCE_VERIFIED, DecisionStatus.VALIDATED}:
            self.evidence_store.require_all(decision.evidence_ids)

        if target is DecisionStatus.VALIDATED:
            result_by_id = {result.result_id: result for result in validation_results}
            missing = set(decision.validation_result_ids) - result_by_id.keys()
            if not decision.validation_result_ids or missing:
                raise InvalidDecisionTransition(
                    "VALIDATED requires all referenced validation results"
                )
            if any(
                result_by_id[result_id].status is not ValidationStatus.PASS
                for result_id in decision.validation_result_ids
            ):
                raise InvalidDecisionTransition("VALIDATED requires PASS validation results")

        return decision.model_copy(
            update={
                "status": target,
                "history": [
                    *decision.history,
                    DecisionTransition(
                        from_status=decision.status,
                        to_status=target,
                        reason=reason,
                    ),
                ],
            }
        )
