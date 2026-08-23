from __future__ import annotations

from typing import Protocol

from ai_pcb.models.architecture import (
    ArchitectureReview,
    ArchitectureReviewFinding,
    ArchitectureReviewStatus,
)
from ai_pcb.models.components import CandidateEvidenceStatus, CandidateViability
from ai_pcb.models.spec import RequirementStatus
from ai_pcb.models.state import DesignState
from ai_pcb.models.validation import ValidationSeverity, ValidationStatus


class ArchitectureReviewer(Protocol):
    def review(self, state: DesignState, *, attempt: int) -> ArchitectureReview: ...


class IndependentArchitectureReviewer:
    """Deterministic fail-closed review, independent of architecture proposal generation."""

    def review(self, state: DesignState, *, attempt: int) -> ArchitectureReview:
        if state.architecture is None or state.architecture_decision is None:
            return ArchitectureReview(
                review_id=f"architecture-review-a{attempt}",
                candidate_id="missing-architecture",
                attempt=attempt,
                status=ArchitectureReviewStatus.REJECTED,
                correction_target="architecture",
                findings=[
                    ArchitectureReviewFinding(
                        finding_id=f"missing-architecture-a{attempt}",
                        status=ValidationStatus.FAIL,
                        severity=ValidationSeverity.CRITICAL,
                        category="architecture",
                        description="No selected architecture exists for review.",
                    )
                ],
            )
        architecture = state.architecture
        findings: list[ArchitectureReviewFinding] = []
        roles = {block.role for block in architecture.functional_blocks}
        required_roles = {item.role for item in state.specialization_context().architecture_blocks}
        if "audio_conversion" in required_roles:
            required_roles.remove("audio_conversion")
            if not roles.intersection({"adc", "dac", "audio_codec", "dsp_processor"}):
                required_roles.add("audio_conversion")
        for role in sorted(required_roles - roles):
            findings.append(
                ArchitectureReviewFinding(
                    finding_id=f"missing-block-{role}-a{attempt}",
                    status=ValidationStatus.FAIL,
                    severity=ValidationSeverity.CRITICAL,
                    category="specialization_coverage",
                    description=f"Resolved specialization block guidance was omitted: {role}.",
                )
            )
        for constraint in architecture.hard_constraints:
            evaluation = next(
                (
                    item
                    for candidate in state.architecture_candidates
                    if candidate.candidate_id == state.architecture_decision.selected_candidate_id
                    for item in candidate.evaluation.criteria
                    if item.criterion_id.endswith(constraint.constraint_id)
                ),
                None,
            )
            if evaluation is not None and evaluation.status is ValidationStatus.FAIL:
                findings.append(
                    ArchitectureReviewFinding(
                        finding_id=f"hard-failure-{constraint.constraint_id}-a{attempt}",
                        status=ValidationStatus.FAIL,
                        severity=ValidationSeverity.CRITICAL,
                        category="hard_constraint",
                        description=evaluation.rationale,
                    )
                )
            elif constraint.status is RequirementStatus.UNKNOWN and constraint.critical:
                findings.append(
                    ArchitectureReviewFinding(
                        finding_id=f"hard-unknown-{constraint.constraint_id}-a{attempt}",
                        status=ValidationStatus.UNKNOWN,
                        severity=ValidationSeverity.CRITICAL,
                        category="hard_constraint",
                        description=(
                            "Critical architecture constraint is unresolved: "
                            f"{constraint.description}"
                        ),
                    )
                )
        for candidate in state.component_candidates:
            if not candidate.identity_source_ids:
                findings.append(
                    ArchitectureReviewFinding(
                        finding_id=f"unsupported-part-{candidate.candidate_id}-a{attempt}",
                        status=ValidationStatus.FAIL,
                        severity=ValidationSeverity.CRITICAL,
                        category="unsupported_part_number",
                        description=(
                            "Part number lacks retrieved identity evidence: "
                            f"{candidate.part_number}"
                        ),
                    )
                )
            if candidate.evidence_status is not CandidateEvidenceStatus.EVIDENCE_VERIFIED:
                findings.append(
                    ArchitectureReviewFinding(
                        finding_id=f"part-evidence-{candidate.candidate_id}-a{attempt}",
                        status=ValidationStatus.UNKNOWN,
                        severity=ValidationSeverity.HIGH,
                        category="evidence_completeness",
                        description=(
                            "Candidate remains identity-known only: "
                            f"{candidate.part_number}"
                        ),
                        affected_ids=[candidate.candidate_id],
                    )
                )
        for component_evaluation in state.component_evaluations:
            if component_evaluation.viability is CandidateViability.REJECTED:
                findings.append(
                    ArchitectureReviewFinding(
                        finding_id=(
                            f"candidate-rejected-{component_evaluation.candidate_id}-a{attempt}"
                        ),
                        status=ValidationStatus.FAIL,
                        severity=ValidationSeverity.CRITICAL,
                        category="component_hard_constraint",
                        description="A rejected component candidate was retained as selected.",
                        affected_ids=[component_evaluation.candidate_id],
                    )
                )
        if state.latency_budget is None or state.latency_budget.total.status.value == "UNKNOWN":
            findings.append(
                ArchitectureReviewFinding(
                    finding_id=f"latency-unresolved-a{attempt}",
                    status=ValidationStatus.UNKNOWN,
                    severity=ValidationSeverity.HIGH,
                    category="latency",
                    description="Critical latency terms remain explicit UNKNOWN pending evidence.",
                )
            )
        if state.computational_budget is None or not state.computational_budget.evidence_ids:
            findings.append(
                ArchitectureReviewFinding(
                    finding_id=f"fxlms-unresolved-a{attempt}",
                    status=ValidationStatus.UNKNOWN,
                    severity=ValidationSeverity.HIGH,
                    category="dsp_suitability",
                    description="FxLMS compute and memory suitability lacks candidate evidence.",
                )
            )
        rejected = any(finding.blocks_acceptance for finding in findings)
        selected_candidate_id = (
            state.architecture_decision.selected_candidate_id or "missing-selected-candidate"
        )
        return ArchitectureReview(
            review_id=f"architecture-review-a{attempt}",
            candidate_id=selected_candidate_id,
            attempt=attempt,
            status=(
                ArchitectureReviewStatus.REJECTED if rejected else ArchitectureReviewStatus.ACCEPTED
            ),
            findings=findings,
            correction_target="architecture" if rejected else None,
        )
