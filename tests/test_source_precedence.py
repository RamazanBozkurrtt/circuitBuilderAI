from __future__ import annotations

from ai_pcb.evidence.precedence import order_for_conflict_review
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import (
    EngineeringEvidenceCandidate,
    RetrievalMethod,
    RetrievalScores,
)


def item(identifier: str, source: EvidenceSource, revision: str) -> EngineeringEvidenceCandidate:
    return EngineeringEvidenceCandidate(
        evidence_candidate_id=f"candidate-{identifier}",
        chunk_id=f"chunk-{identifier}",
        document_id=f"doc-{identifier}",
        source_file=f"{identifier}.pdf",
        source_type=source,
        manufacturer="Example Semiconductor",
        document_title=identifier,
        document_revision=revision,
        document_hash="b" * 64,
        page=1,
        locator="page=1",
        extracted_text=f"Conflicting condition from {identifier}",
        scores=RetrievalScores(fused=0.5),
        retrieval_method=RetrievalMethod.HYBRID,
    )


def test_source_precedence_orders_but_never_discards_conflicts() -> None:
    application_note = item("specialized-note", EvidenceSource.APPLICATION_NOTE, "C")
    datasheet = item("datasheet", EvidenceSource.DATASHEET, "B")
    ordered = order_for_conflict_review([application_note, datasheet])
    assert ordered == [datasheet, application_note]
    assert set(candidate.document_id for candidate in ordered) == {
        datasheet.document_id,
        application_note.document_id,
    }
