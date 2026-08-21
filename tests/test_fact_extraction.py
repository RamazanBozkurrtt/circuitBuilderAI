from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ai_pcb.evidence.errors import FactExtractionError
from ai_pcb.evidence.facts import extract_engineering_fact
from ai_pcb.evidence.retrieval import promote_retrieval_candidate
from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.llm.base import StructuredLLMError
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import (
    EngineeringEvidenceCandidate,
    EngineeringFactCandidate,
    FactConflict,
    FactStatus,
    RetrievalMethod,
    RetrievalScores,
)


def candidate(identifier: str, text: str) -> EngineeringEvidenceCandidate:
    suffix = identifier.removeprefix("candidate-")
    return EngineeringEvidenceCandidate(
        evidence_candidate_id=identifier,
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        source_file=f"datasheets/{suffix}.pdf",
        source_type=EvidenceSource.DATASHEET,
        manufacturer="Example",
        part_number="PART1",
        document_title="Synthetic Datasheet",
        document_revision="A",
        document_hash="a" * 64,
        page=3,
        section="POWER REQUIREMENTS",
        locator="page=3;bbox(1.00,2.00,3.00,4.00)",
        extracted_text=text,
        scores=RetrievalScores(dense=0.8, lexical=1.2, fused=0.9),
        retrieval_method=RetrievalMethod.HYBRID,
    )


class ReturningLLM:
    def __init__(self, result: EngineeringFactCandidate) -> None:
        self.result = result

    def complete(self, *args: Any, **kwargs: Any) -> EngineeringFactCandidate:
        return self.result


class MalformedLLM:
    def complete(self, *args: Any, **kwargs: Any) -> EngineeringFactCandidate:
        raise StructuredLLMError("bad output")


def test_insufficient_evidence_does_not_become_fact() -> None:
    result = extract_engineering_fact(
        ReturningLLM(EngineeringFactCandidate(status=FactStatus.INSUFFICIENT_EVIDENCE)),
        question="What is AVDD?",
        evidence=[candidate("candidate-one", "Only DVDD is described.")],
    )
    assert result.status is FactStatus.INSUFFICIENT_EVIDENCE
    assert result.value is None
    assert result.evidence_ids == []


def test_conflicting_evidence_is_preserved() -> None:
    first = candidate("candidate-one", "DVDD is 1.2 V.")
    second = candidate("candidate-two", "DVDD is 1.1 V.")
    conflict = EngineeringFactCandidate(
        fact_type="supply_voltage",
        subject="DVDD",
        evidence_ids=[first.evidence_candidate_id, second.evidence_candidate_id],
        conflicts=[
            FactConflict(
                description="Incompatible DVDD values under the same stated conditions",
                evidence_ids=[first.evidence_candidate_id, second.evidence_candidate_id],
            )
        ],
        status=FactStatus.CONFLICTING_EVIDENCE,
    )
    result = extract_engineering_fact(
        ReturningLLM(conflict), question="What is DVDD?", evidence=[first, second]
    )
    assert result.status is FactStatus.CONFLICTING_EVIDENCE
    assert set(result.evidence_ids) == {"candidate-one", "candidate-two"}


def test_unsupported_claim_and_malformed_output_fail_closed() -> None:
    supplied = candidate("candidate-one", "DVDD is 1.2 V.")
    unsupported = EngineeringFactCandidate(
        fact_type="supply_voltage",
        subject="DVDD",
        value="1.0",
        unit="V",
        evidence_ids=["candidate-never-supplied"],
        confidence=0.9,
        status=FactStatus.EXTRACTED,
    )
    with pytest.raises(FactExtractionError, match="not supplied"):
        extract_engineering_fact(
            ReturningLLM(unsupported), question="What is DVDD?", evidence=[supplied]
        )
    with pytest.raises(FactExtractionError, match="malformed"):
        extract_engineering_fact(
            MalformedLLM(), question="What is DVDD?", evidence=[supplied]
        )


def test_only_reviewed_retrieval_candidate_can_be_promoted(tmp_path: Path) -> None:
    item = candidate("candidate-one", "DVDD is 1.2 V.")
    store = EvidenceStore(tmp_path / "evidence")
    with pytest.raises(ValueError, match="reviewed"):
        promote_retrieval_candidate(
            item,
            store,
            normalized_fact="DVDD nominal voltage is 1.2 V",
            title="DVDD voltage",
            reviewed=False,
        )
    fact = EngineeringFactCandidate(
        fact_type="supply_voltage",
        subject="DVDD",
        value="1.2",
        unit="V",
        evidence_ids=[item.evidence_candidate_id],
        status=FactStatus.EXTRACTED,
    )
    with pytest.raises(TypeError, match="retrieved evidence"):
        promote_retrieval_candidate(  # type: ignore[arg-type]
            fact,
            store,
            normalized_fact="unsupported",
            title="unsupported",
            reviewed=True,
        )
    promoted = promote_retrieval_candidate(
        item,
        store,
        normalized_fact="DVDD nominal voltage is 1.2 V",
        title="DVDD voltage",
        reviewed=True,
    )
    assert promoted.confidence is None
    assert promoted.provenance.locator == item.locator
