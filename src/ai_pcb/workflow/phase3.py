from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ai_pcb.architecture.analysis import (
    build_candidate_computational_budget,
    build_computational_budget,
    build_evidence_aware_latency_budget,
    build_latency_budget,
)
from ai_pcb.architecture.synthesis import ArchitectureSynthesizer
from ai_pcb.components.discovery import EvidenceGroundedCandidateDiscovery
from ai_pcb.components.evaluation import ComponentEvaluator
from ai_pcb.components.requirements import ComponentRequirementDeriver
from ai_pcb.models.architecture import (
    ArchitectureDecision,
    ArchitectureReviewStatus,
)
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    CandidateViability,
    ComponentCategory,
    ComponentSelection,
)
from ai_pcb.models.decision import DecisionAlternative, EngineeringDecision
from ai_pcb.models.state import DesignState, WorkflowStage
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    VerificationReport,
)
from ai_pcb.validation.architecture import (
    ArchitectureReviewer,
    IndependentArchitectureReviewer,
)
from ai_pcb.workflow.transitions import transition_state


class Phase3Context(TypedDict):
    design_state: DesignState
    attempt: int
    route: str
    correction_notes: list[str]


class Phase3Workflow:
    """Bounded Phase 3 proposal/evidence/evaluation/independent-review graph."""

    def __init__(
        self,
        *,
        max_iterations: int,
        candidate_discovery: EvidenceGroundedCandidateDiscovery | None = None,
        reviewer: ArchitectureReviewer | None = None,
        checkpoint: Callable[[DesignState], None] | None = None,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("Phase 3 requires at least one bounded review attempt")
        self.max_iterations = max_iterations
        self.synthesizer = ArchitectureSynthesizer()
        self.requirement_deriver = ComponentRequirementDeriver()
        self.candidate_discovery = candidate_discovery or EvidenceGroundedCandidateDiscovery(None)
        self.evaluator = ComponentEvaluator()
        self.reviewer = reviewer or IndependentArchitectureReviewer()
        self.checkpoint = checkpoint
        self.graph = self._build_graph()

    def invoke(self, state: DesignState) -> DesignState:
        result = self.graph.invoke(
            {
                "design_state": state,
                "attempt": 1,
                "route": "propose",
                "correction_notes": [],
            }
        )
        return DesignState.model_validate(result["design_state"])

    def _build_graph(self) -> Any:
        builder = StateGraph(Phase3Context)
        builder.add_node("propose", self._propose)  # type: ignore[call-overload]
        builder.add_node("components", self._components)  # type: ignore[call-overload]
        builder.add_node("review", self._review)  # type: ignore[call-overload]
        builder.add_node("correction", self._correction)  # type: ignore[call-overload]
        builder.add_node("blocked", self._blocked)  # type: ignore[call-overload]
        builder.add_edge(START, "propose")
        builder.add_edge("propose", "components")
        builder.add_edge("components", "review")
        builder.add_conditional_edges(
            "review", self._route, {"complete": END, "correction": "correction"}
        )
        builder.add_conditional_edges(
            "correction", self._route, {"propose": "propose", "blocked": "blocked"}
        )
        builder.add_edge("blocked", END)
        return builder.compile()

    @staticmethod
    def _route(context: Phase3Context) -> Hashable:
        return context["route"]

    def _propose(self, context: Phase3Context) -> Phase3Context:
        state = context["design_state"]
        if state.workflow_stage is WorkflowStage.SPECIFICATION:
            state = transition_state(
                state,
                WorkflowStage.ARCHITECTURE,
                "Phase 3 architecture synthesis",
                require_verification=False,
            )
        elif state.workflow_stage is WorkflowStage.COMPONENT_SELECTION:
            state = transition_state(
                state,
                WorkflowStage.ARCHITECTURE,
                "independent review requested architecture correction",
                require_verification=False,
            )
        candidates = self.synthesizer.synthesize(
            state.master_spec,
            state.specialization_context(),
            attempt=context["attempt"],
            correction_notes=context["correction_notes"],
        )
        viable = [candidate for candidate in candidates if candidate.evaluation.viable]
        selected = viable[0] if viable else candidates[0]
        decision = ArchitectureDecision(
            decision_id=f"architecture-decision-a{context['attempt']}",
            selected_candidate_id=selected.candidate_id,
            viable_alternative_ids=[
                candidate.candidate_id
                for candidate in viable
                if candidate.candidate_id != selected.candidate_id
            ],
            rejected_candidate_ids=[
                candidate.candidate_id
                for candidate in candidates
                if not candidate.evaluation.viable
            ],
            rejection_reasons=[
                item.rationale
                for candidate in candidates
                if not candidate.evaluation.viable
                for item in candidate.evaluation.criteria
                if item.status is ValidationStatus.FAIL
            ],
            risk_ids=[risk.risk_id for risk in selected.architecture.risks],
            unresolved_trade_offs=selected.evaluation.unresolved_trade_offs,
        )
        engineering_decision = EngineeringDecision(
            decision_id=decision.decision_id,
            title="Provisional system architecture",
            statement=f"Propose {selected.architecture.name} for Phase 3 evidence closure.",
            alternatives=[
                DecisionAlternative(name=candidate.architecture.name)
                for candidate in viable
                if candidate.candidate_id != selected.candidate_id
            ],
            risks=[risk.description for risk in selected.architecture.risks],
        )
        updated = state.model_copy(
            update={
                "architecture": selected.architecture,
                "architecture_candidates": [*state.architecture_candidates, *candidates],
                "architecture_decision": decision,
                "decisions": [*state.decisions, engineering_decision],
                "latency_budget": build_latency_budget(),
                "computational_budget": build_computational_budget(state.master_spec),
                "phase3_complete": False,
            }
        )
        self._checkpoint(updated)
        return {**context, "design_state": updated, "route": "components"}

    def _components(self, context: Phase3Context) -> Phase3Context:
        state = context["design_state"]
        if state.workflow_stage is not WorkflowStage.COMPONENT_SELECTION:
            state = transition_state(
                state,
                WorkflowStage.COMPONENT_SELECTION,
                "derive and evaluate major component requirements",
                require_verification=False,
            )
        specialization_context = state.specialization_context()
        requirements = self.requirement_deriver.derive(state.master_spec, specialization_context)
        discovery = self.candidate_discovery.discover(requirements, specialization_context)
        evaluations = [
            self.evaluator.evaluate(candidate, requirements, specialization_context)
            for candidate in discovery.candidates
        ]
        selections: list[ComponentSelection] = []
        for category in dict.fromkeys(item.category for item in requirements):
            category_candidates = [
                candidate
                for candidate in discovery.candidates
                if candidate.category is category
            ]
            provisional = None
            if category is ComponentCategory.DSP_PROCESSOR:
                provisional = next(
                    (
                        candidate
                        for candidate in category_candidates
                        if candidate.evidence_status
                        is CandidateEvidenceStatus.EVIDENCE_VERIFIED
                        and next(
                            evaluation
                            for evaluation in evaluations
                            if evaluation.candidate_id == candidate.candidate_id
                        ).viability
                        is not CandidateViability.REJECTED
                    ),
                    None,
                )
            selections.append(
                ComponentSelection(
                    selection_id=f"selection-{category.value.lower()}",
                    category=category,
                    selected_candidate_id=(
                        provisional.candidate_id if provisional is not None else None
                    ),
                    viable_alternative_ids=[
                        candidate.candidate_id
                        for candidate in category_candidates
                        if provisional is None
                        or candidate.candidate_id != provisional.candidate_id
                    ],
                    evidence_ids=(
                        provisional.verified_evidence_ids if provisional is not None else []
                    ),
                    unresolved_trade_offs=[
                        (
                            "PROVISIONALLY_SELECTED: architecture-compatible manufacturer "
                            "evidence exists, but final FxLMS workload validation is unresolved."
                            if provisional is not None
                            else "No component is approved until manufacturer evidence and "
                            "unresolved hard requirements permit safe closure."
                        )
                    ],
                )
            )
        dsp_candidate = next(
            (
                candidate
                for candidate in discovery.candidates
                if any(
                    selection.selected_candidate_id == candidate.candidate_id
                    for selection in selections
                )
                and candidate.category is ComponentCategory.DSP_PROCESSOR
            ),
            None,
        )
        architecture = state.architecture
        architecture_decision = state.architecture_decision
        evidenced_codecs = [
            candidate
            for candidate in discovery.candidates
            if candidate.category is ComponentCategory.AUDIO_CODEC
            and candidate.evidence_status is CandidateEvidenceStatus.EVIDENCE_VERIFIED
            and next(
                evaluation
                for evaluation in evaluations
                if evaluation.candidate_id == candidate.candidate_id
            ).viability
            is not CandidateViability.REJECTED
        ]
        if evidenced_codecs and architecture_decision is not None:
            codec_architecture = next(
                (
                    candidate
                    for candidate in reversed(state.architecture_candidates)
                    if candidate.architecture.topology == "multichannel_codec"
                ),
                None,
            )
            if codec_architecture is not None:
                architecture = codec_architecture.architecture
                separate = next(
                    (
                        candidate.candidate_id
                        for candidate in reversed(state.architecture_candidates)
                        if candidate.architecture.topology == "separate_converters"
                    ),
                    None,
                )
                integrated = next(
                    (
                        candidate.candidate_id
                        for candidate in reversed(state.architecture_candidates)
                        if candidate.architecture.topology == "integrated_converters"
                    ),
                    None,
                )
                architecture_decision = architecture_decision.model_copy(
                    update={
                        "selected_candidate_id": codec_architecture.candidate_id,
                        "viable_alternative_ids": [separate] if separate else [],
                        "rejected_candidate_ids": [integrated] if integrated else [],
                        "rejection_reasons": [
                            "No trusted candidate evidence establishes integrated DSP converter "
                            "capacity for the required four input and four output channels."
                        ],
                        "evidence_ids": list(
                            dict.fromkeys(
                                evidence_id
                                for candidate in evidenced_codecs
                                for evidence_id in candidate.verified_evidence_ids
                            )
                        ),
                        "unresolved_trade_offs": [
                            "PCM3168A and AD1938 both establish codec channel feasibility; "
                            "sample rate, bit depth, microphone interface, latency choice, and "
                            "clock implementation remain unresolved.",
                            "The separate-converter alternative remains viable but lacks an "
                            "evidenced DAC candidate in the current corpus.",
                        ],
                    }
                )
        updated = state.model_copy(
            update={
                "architecture": architecture,
                "architecture_decision": architecture_decision,
                "component_requirements": requirements,
                "component_candidates": discovery.candidates,
                "component_evaluations": evaluations,
                "components": selections,
                "evidence_acquisition_requirements": discovery.evidence_requirements,
                "computational_budget": (
                    build_candidate_computational_budget(state.master_spec, dsp_candidate)
                    if dsp_candidate is not None
                    else state.computational_budget
                ),
                "latency_budget": build_evidence_aware_latency_budget(
                    discovery.candidates
                ),
            }
        )
        self._checkpoint(updated)
        return {**context, "design_state": updated, "route": "review"}

    def _review(self, context: Phase3Context) -> Phase3Context:
        state = context["design_state"]
        review = self.reviewer.review(state, attempt=context["attempt"])
        report = self._review_report(review)
        complete = review.status is ArchitectureReviewStatus.ACCEPTED
        updated = state.model_copy(
            update={
                "architecture_reviews": [*state.architecture_reviews, review],
                "verification_reports": [*state.verification_reports, report],
                "phase3_complete": complete,
            }
        )
        self._checkpoint(updated)
        if complete:
            return {**context, "design_state": updated, "route": "complete"}
        notes = [finding.description for finding in review.findings if finding.blocks_acceptance]
        return {
            **context,
            "design_state": updated,
            "route": "correction",
            "correction_notes": notes,
        }

    def _correction(self, context: Phase3Context) -> Phase3Context:
        if context["attempt"] >= self.max_iterations:
            return {**context, "route": "blocked"}
        return {**context, "attempt": context["attempt"] + 1, "route": "propose"}

    def _blocked(self, context: Phase3Context) -> Phase3Context:
        state = context["design_state"]
        blockers = [
            *state.blockers,
            f"Phase 3 architecture review exhausted {self.max_iterations} attempts",
        ]
        if state.workflow_stage is not WorkflowStage.BLOCKED:
            state = transition_state(
                state.model_copy(update={"blockers": blockers}),
                WorkflowStage.BLOCKED,
                blockers[-1],
                require_verification=False,
            )
        updated = state.model_copy(update={"phase3_complete": False})
        self._checkpoint(updated)
        return {**context, "design_state": updated, "route": "blocked"}

    @staticmethod
    def _review_report(review: Any) -> VerificationReport:
        results = [
            ValidationResult(
                result_id=finding.finding_id,
                validator="independent_architecture_review",
                status=finding.status,
                severity=finding.severity,
                summary=finding.description,
                evidence_ids=finding.evidence_ids,
            )
            for finding in review.findings
        ]
        if not results:
            results = [
                ValidationResult(
                    result_id=f"architecture-review-pass-a{review.attempt}",
                    validator="independent_architecture_review",
                    status=ValidationStatus.PASS,
                    severity=ValidationSeverity.INFO,
                    summary="Independent Phase 3 architecture review passed.",
                )
            ]
        return VerificationReport(
            report_id=review.review_id,
            stage="COMPONENT_SELECTION",
            results=results,
            can_advance=not any(result.blocks_progression for result in results),
        )

    def _checkpoint(self, state: DesignState) -> None:
        if self.checkpoint is not None:
            self.checkpoint(state)
