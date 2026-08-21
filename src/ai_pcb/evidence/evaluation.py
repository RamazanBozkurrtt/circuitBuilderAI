from __future__ import annotations

from collections.abc import Sequence

from ai_pcb.evidence.retrieval import EvidenceRetriever
from ai_pcb.models.knowledge import RetrievalEvaluationCase, RetrievalEvaluationMetrics


def evaluate_retrieval(
    retriever: EvidenceRetriever, cases: Sequence[RetrievalEvaluationCase]
) -> RetrievalEvaluationMetrics:
    hits = 0
    reciprocal_rank = 0.0
    for case in cases:
        results = retriever.search(case.query)
        rank = next(
            (
                index
                for index, result in enumerate(results, start=1)
                if result.document_id == case.expected_document_id
                and (case.expected_page is None or result.page == case.expected_page)
                and (case.expected_chunk_id is None or result.chunk_id == case.expected_chunk_id)
            ),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_rank += 1 / rank
    count = len(cases)
    return RetrievalEvaluationMetrics(
        cases=count,
        recall_at_k=hits / count if count else 0.0,
        mean_reciprocal_rank=reciprocal_rank / count if count else 0.0,
    )
