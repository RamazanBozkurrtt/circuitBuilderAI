from __future__ import annotations

from ai_pcb.models.architecture import ConstraintKind, ValueStatus
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    CandidateViability,
    ComponentCandidate,
    ComponentCriterionEvaluation,
    ComponentEvaluation,
    ComponentRequirement,
)
from ai_pcb.models.spec import RequirementStatus
from ai_pcb.models.validation import ValidationStatus
from ai_pcb.specializations.models import ResolvedSpecializationContext


class ComponentEvaluator:
    def evaluate(
        self,
        candidate: ComponentCandidate,
        requirements: list[ComponentRequirement],
        context: ResolvedSpecializationContext,
    ) -> ComponentEvaluation:
        applicable = [item for item in requirements if item.category is candidate.category]
        facts = {fact.attribute: fact for fact in candidate.facts}
        criteria: list[ComponentCriterionEvaluation] = []
        for requirement in applicable:
            fact = facts.get(requirement.attribute)
            status = ValidationStatus.UNKNOWN
            rationale = "Required manufacturer fact has not been extracted and verified."
            score = None
            evidence_ids: list[str] = []
            if fact is not None and fact.value.status is not ValueStatus.UNKNOWN:
                evidence_ids = fact.value.evidence_ids
                if requirement.status is RequirementStatus.UNKNOWN:
                    status = ValidationStatus.UNKNOWN
                    rationale = (
                        "The candidate fact is known but the design requirement is unresolved."
                    )
                elif fact.value.value == requirement.value:
                    status = ValidationStatus.PASS
                    rationale = "The evidenced candidate fact satisfies the explicit requirement."
                    score = 1.0
                elif (
                    isinstance(fact.value.value, (int, float))
                    and isinstance(requirement.value, (int, float))
                    and requirement.attribute
                    in {
                        "channel_count",
                        "input_channels",
                        "output_channels",
                        "audio_input_capacity",
                        "audio_output_capacity",
                    }
                ):
                    passed = float(fact.value.value) >= float(requirement.value)
                    status = ValidationStatus.PASS if passed else ValidationStatus.FAIL
                    rationale = (
                        "Candidate capacity meets the minimum requirement."
                        if passed
                        else "Candidate capacity is below the hard requirement."
                    )
                    score = 1.0 if passed else 0.0
                else:
                    status = ValidationStatus.FAIL
                    rationale = "The evidenced candidate fact does not match the requirement."
                    score = 0.0
            criteria.append(
                ComponentCriterionEvaluation(
                    criterion_id=f"{candidate.candidate_id}-{requirement.attribute}",
                    dimension=requirement.description,
                    kind=requirement.kind,
                    status=status,
                    rationale=rationale,
                    score=score,
                    evidence_ids=evidence_ids,
                )
            )
        covered = {item.dimension.casefold() for item in criteria}
        for guidance in context.evaluation_criteria:
            if (
                guidance.applicable_categories
                and candidate.category.value not in guidance.applicable_categories
            ):
                continue
            if guidance.dimension.casefold() in covered:
                continue
            criteria.append(
                ComponentCriterionEvaluation(
                    criterion_id=f"{candidate.candidate_id}-{guidance.criterion_id}",
                    dimension=guidance.dimension,
                    kind=ConstraintKind.OPTIMIZATION_OBJECTIVE,
                    status=ValidationStatus.UNKNOWN,
                    rationale="No evidenced comparison value is available.",
                    weight=guidance.default_weight,
                )
            )
        hard_failures = [
            item
            for item in criteria
            if item.kind is ConstraintKind.HARD_CONSTRAINT and item.status is ValidationStatus.FAIL
        ]
        hard_unknowns = [
            item
            for item in criteria
            if item.kind is ConstraintKind.HARD_CONSTRAINT
            and item.status is ValidationStatus.UNKNOWN
        ]
        if hard_failures:
            viability = CandidateViability.REJECTED
        elif (
            hard_unknowns
            or candidate.evidence_status is not CandidateEvidenceStatus.EVIDENCE_VERIFIED
        ):
            viability = CandidateViability.EVIDENCE_REQUIRED
        else:
            viability = CandidateViability.VIABLE
        scored = [
            item
            for item in criteria
            if item.kind is ConstraintKind.OPTIMIZATION_OBJECTIVE and item.score is not None
        ]
        weight_sum = sum(item.weight for item in scored)
        weighted = (
            sum((item.score or 0.0) * item.weight for item in scored) / weight_sum
            if weight_sum
            else None
        )
        return ComponentEvaluation(
            evaluation_id=f"evaluation-{candidate.candidate_id}",
            candidate_id=candidate.candidate_id,
            criteria=criteria,
            viability=viability,
            weighted_optimization_score=weighted,
            rejection_reasons=[item.rationale for item in hard_failures],
            unresolved_trade_offs=[item.rationale for item in hard_unknowns],
        )
