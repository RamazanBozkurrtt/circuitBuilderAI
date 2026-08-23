from __future__ import annotations

from collections.abc import Sequence

from ai_pcb.evidence.retrieval import EvidenceRetriever
from ai_pcb.models.knowledge import (
    RetrievalCorpusMetrics,
    RetrievalEvaluationCase,
    RetrievalEvaluationFailure,
    RetrievalEvaluationMetrics,
    RetrievalFailureCategory,
)


def evaluate_retrieval(
    retriever: EvidenceRetriever, cases: Sequence[RetrievalEvaluationCase]
) -> RetrievalEvaluationMetrics:
    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    reciprocal_rank = 0.0
    failures: list[RetrievalEvaluationFailure] = []
    for case in cases:
        results = retriever.search(case.query.model_copy(update={"top_k": 25}))
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
        if rank is not None and rank <= 5:
            hits_at_1 += int(rank <= 1)
            hits_at_3 += int(rank <= 3)
            hits_at_5 += int(rank <= 5)
            reciprocal_rank += 1 / rank
        else:
            expected_document = [
                result for result in results if result.document_id == case.expected_document_id
            ]
            query = case.query.query.casefold()
            if not results:
                category = RetrievalFailureCategory.DOCUMENT_PARSING_ISSUE
                description = "No indexed result was returned for the engineering query."
            elif not expected_document:
                category = (
                    RetrievalFailureCategory.METADATA_ISSUE
                    if case.query.part_number or case.query.document_id
                    else RetrievalFailureCategory.HYBRID_RANKING_ISSUE
                )
                description = "The expected document was absent from the top 25 results."
            elif case.expected_page is not None and not any(
                result.page == case.expected_page for result in expected_document
            ):
                category = (
                    RetrievalFailureCategory.TABLE_EXTRACTION_FAILURE
                    if any(term in query for term in ("group delay", "noise", "power supply"))
                    else RetrievalFailureCategory.CROSS_PAGE_CONTEXT_ISSUE
                )
                description = "The expected document ranked, but the curated page did not."
            else:
                category = RetrievalFailureCategory.HYBRID_RANKING_ISSUE
                description = "The curated location ranked below Recall@5."
            failures.append(
                RetrievalEvaluationFailure(
                    case_id=case.case_id,
                    category=category,
                    description=description,
                )
            )
    count = len(cases)
    return RetrievalEvaluationMetrics(
        cases=count,
        recall_at_1=hits_at_1 / count if count else 0.0,
        recall_at_3=hits_at_3 / count if count else 0.0,
        recall_at_5=hits_at_5 / count if count else 0.0,
        recall_at_k=hits_at_5 / count if count else 0.0,
        mean_reciprocal_rank=reciprocal_rank / count if count else 0.0,
        failures=failures,
    )


def evaluate_retrieval_corpora(
    retriever: EvidenceRetriever,
    *,
    synthetic_cases: Sequence[RetrievalEvaluationCase],
    real_datasheet_cases: Sequence[RetrievalEvaluationCase],
    meaningful_real_case_count: int = 20,
) -> RetrievalCorpusMetrics:
    return RetrievalCorpusMetrics(
        synthetic=evaluate_retrieval(retriever, synthetic_cases),
        real_datasheets=evaluate_retrieval(retriever, real_datasheet_cases),
        real_corpus_meaningful=len(real_datasheet_cases) >= meaningful_real_case_count,
    )
