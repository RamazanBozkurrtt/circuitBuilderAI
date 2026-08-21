from __future__ import annotations

from collections.abc import Mapping

from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import EngineeringEvidenceCandidate

DEFAULT_SOURCE_PRECEDENCE: dict[EvidenceSource, int] = {
    EvidenceSource.DATASHEET: 300,
    EvidenceSource.REFERENCE_DESIGN: 200,
    EvidenceSource.APPLICATION_NOTE: 200,
    EvidenceSource.USER_SPEC: 100,
    EvidenceSource.SIMULATION: 100,
    EvidenceSource.EDA_VALIDATION: 100,
    EvidenceSource.RULE_ENGINE: 100,
}


def order_for_conflict_review(
    candidates: list[EngineeringEvidenceCandidate],
    precedence: Mapping[EvidenceSource, int] | None = None,
) -> list[EngineeringEvidenceCandidate]:
    """Order candidates for review without removing conflicts or comparing unlike conditions."""
    ranking = precedence or DEFAULT_SOURCE_PRECEDENCE

    def score(candidate: EngineeringEvidenceCandidate) -> int:
        configured = ranking.get(candidate.source_type, 0)
        return configured if candidate.manufacturer else min(configured, 100)

    return sorted(
        candidates,
        key=lambda candidate: (
            -score(candidate),
            candidate.document_id,
            candidate.page,
            candidate.chunk_id,
        ),
    )
