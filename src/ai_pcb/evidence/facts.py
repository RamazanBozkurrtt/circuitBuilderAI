from __future__ import annotations

import json
from collections.abc import Sequence

from ai_pcb.evidence.errors import FactExtractionError
from ai_pcb.llm.base import StructuredLLM, StructuredLLMError
from ai_pcb.models.knowledge import (
    EngineeringEvidenceCandidate,
    EngineeringFactCandidate,
    FactStatus,
)

FACT_EXTRACTION_SYSTEM_PROMPT = """You extract engineering facts only from the supplied evidence
candidates.
Never use memory, prior knowledge, assumptions, or unstated calculations.
Every extracted value must cite the supplied evidence_candidate_id that directly supports it.
When the evidence cannot answer the question, return status INSUFFICIENT_EVIDENCE with no value
and no evidence_ids. When sources give incompatible values under the same conditions, return
CONFLICTING_EVIDENCE and preserve every conflicting evidence reference. Do not resolve conflicts
based only on document date or retrieval score. Retrieval score is not engineering confidence.
"""


def extract_engineering_fact(
    llm: StructuredLLM,
    *,
    question: str,
    evidence: Sequence[EngineeringEvidenceCandidate],
    max_candidates: int = 8,
    max_characters: int = 16_000,
) -> EngineeringFactCandidate:
    """Run one bounded, schema-validated, evidence-only extraction request."""
    if not question.strip():
        raise ValueError("engineering question cannot be empty")
    if max_candidates < 1 or max_characters < 100:
        raise ValueError("fact extraction bounds must be positive")
    selected = list(evidence[:max_candidates])
    payload: list[dict[str, object]] = []
    used = 0
    for candidate in selected:
        remaining = max_characters - used
        if remaining <= 0:
            break
        text = candidate.extracted_text[:remaining]
        used += len(text)
        payload.append(
            {
                "evidence_candidate_id": candidate.evidence_candidate_id,
                "document": candidate.document_title,
                "revision": candidate.document_revision,
                "page": candidate.page,
                "section": candidate.section,
                "locator": candidate.locator,
                "source_type": candidate.source_type.value,
                "text": text,
            }
        )
    if not payload:
        return EngineeringFactCandidate(status=FactStatus.INSUFFICIENT_EVIDENCE)
    prompt = json.dumps(
        {"engineering_question": question, "evidence_candidates": payload},
        indent=2,
        ensure_ascii=False,
    )
    try:
        result = llm.complete(
            prompt,
            EngineeringFactCandidate,
            system_prompt=FACT_EXTRACTION_SYSTEM_PROMPT,
        )
    except StructuredLLMError as exc:
        raise FactExtractionError("malformed structured fact extraction result") from exc
    allowed = {str(item["evidence_candidate_id"]) for item in payload}
    unsupported = set(result.evidence_ids) - allowed
    unsupported.update(
        evidence_id
        for conflict in result.conflicts
        for evidence_id in conflict.evidence_ids
        if evidence_id not in allowed
    )
    if unsupported:
        raise FactExtractionError(
            "fact extraction cited evidence that was not supplied: "
            f"{', '.join(sorted(unsupported))}"
        )
    return result
