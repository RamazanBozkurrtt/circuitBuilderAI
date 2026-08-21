from __future__ import annotations

from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    CandidateViability,
    ComponentCandidate,
    ComponentEvaluation,
    ComponentSelection,
)
from ai_pcb.models.decision import DecisionStatus


class InvalidComponentSelectionTransition(ValueError):
    pass


class ComponentSelectionLifecycle:
    def __init__(self, evidence_store: EvidenceStore) -> None:
        self.evidence_store = evidence_store

    def evidence_verify(
        self,
        selection: ComponentSelection,
        candidate: ComponentCandidate,
        evaluation: ComponentEvaluation,
    ) -> ComponentSelection:
        if selection.status is not DecisionStatus.PROPOSED:
            raise InvalidComponentSelectionTransition(
                "only a proposed component selection can be evidence-verified"
            )
        if selection.selected_candidate_id != candidate.candidate_id:
            raise InvalidComponentSelectionTransition(
                "selection and candidate identifiers do not match"
            )
        if evaluation.candidate_id != candidate.candidate_id:
            raise InvalidComponentSelectionTransition(
                "candidate evaluation does not match the selected candidate"
            )
        if candidate.evidence_status is not CandidateEvidenceStatus.EVIDENCE_VERIFIED:
            raise InvalidComponentSelectionTransition(
                "candidate manufacturer evidence has not been verified"
            )
        if evaluation.viability is not CandidateViability.VIABLE:
            raise InvalidComponentSelectionTransition(
                "unresolved or failed hard constraints prevent evidence verification"
            )
        evidence_ids = list(
            dict.fromkeys([*selection.evidence_ids, *candidate.verified_evidence_ids])
        )
        self.evidence_store.require_all(evidence_ids)
        return selection.model_copy(
            update={"status": DecisionStatus.EVIDENCE_VERIFIED, "evidence_ids": evidence_ids}
        )
