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
from ai_pcb.architecture.closure import (
    assess_phase4_readiness,
    build_clock_tree,
    build_microphone_front_end,
    build_power_tree,
    classify_and_close_design_variables,
)
from ai_pcb.architecture.synthesis import ArchitectureSynthesizer
from ai_pcb.components.discovery import EvidenceGroundedCandidateDiscovery
from ai_pcb.components.evaluation import ComponentEvaluator
from ai_pcb.components.requirements import ComponentRequirementDeriver
from ai_pcb.models.architecture import (
    ArchitectureConnection,
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
                candidate for candidate in discovery.candidates if candidate.category is category
            ]
            provisional = None
            preferred_parts = {
                ComponentCategory.DSP_PROCESSOR: "ADSP-21569",
                ComponentCategory.ADC: "ADAU1978",
                ComponentCategory.CLASS_D_AMPLIFIER: "TAS6424-Q1",
                ComponentCategory.POWER_MANAGEMENT: "ADP5054",
            }
            if category in preferred_parts:
                provisional = next(
                    (
                        candidate
                        for candidate in category_candidates
                        if candidate.part_number == preferred_parts[category]
                        if candidate.evidence_status is CandidateEvidenceStatus.EVIDENCE_VERIFIED
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
                        if provisional is None or candidate.candidate_id != provisional.candidate_id
                    ],
                    evidence_ids=(
                        provisional.verified_evidence_ids if provisional is not None else []
                    ),
                    unresolved_trade_offs=[
                        (
                            "PROVISIONALLY_SELECTED: manufacturer evidence and the Phase 3.3 "
                            "design envelope justify architecture use, but this is not a final "
                            "validated component approval."
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
        selected_adc = next(
            (
                candidate
                for candidate in discovery.candidates
                if candidate.part_number == "ADAU1978"
                and candidate.evidence_status is CandidateEvidenceStatus.EVIDENCE_VERIFIED
            ),
            None,
        )
        selected_amplifier = next(
            (
                candidate
                for candidate in discovery.candidates
                if candidate.part_number == "TAS6424-Q1"
            ),
            None,
        )
        if (
            selected_adc is not None
            and selected_amplifier is not None
            and architecture_decision is not None
        ):
            direct_architecture = next(
                (
                    candidate
                    for candidate in reversed(state.architecture_candidates)
                    if candidate.architecture.topology == "separate_converters"
                ),
                None,
            )
            if direct_architecture is not None:
                direct = direct_architecture.architecture
                blocks = [block for block in direct.functional_blocks if block.role != "dac"]
                connections = [
                    connection
                    for connection in direct.connections
                    if "dac" not in {connection.source_block_id, connection.destination_block_id}
                ]
                connections.append(
                    ArchitectureConnection(
                        connection_id="dsp-tdm-to-digital-class-d",
                        source_block_id="dsp_processor",
                        destination_block_id="output_amplification",
                        interface_type="synchronous_tdm4_digital_audio",
                        latency_critical=True,
                        synchronization_required=True,
                    )
                )
                path_evidence = list(
                    dict.fromkeys(
                        [
                            *selected_adc.verified_evidence_ids,
                            *selected_amplifier.verified_evidence_ids,
                        ]
                    )
                )
                revised_risks = []
                for risk in direct.risks:
                    if risk.risk_id.endswith("latency-evidence"):
                        revised_risks.append(
                            risk.model_copy(
                                update={
                                    "description": (
                                        "Converter and amplifier latency are documented; "
                                        "AFE, buffering, DSP, and acoustic delays remain "
                                        "explicitly unknown."
                                    ),
                                    "severity": ValidationSeverity.HIGH,
                                    "affected_blocks": [
                                        "microphone_front_end",
                                        "adc",
                                        "dsp_processor",
                                        "output_amplification",
                                    ],
                                    "mitigation": (
                                        "Close the remaining terms during schematic and "
                                        "firmware verification."
                                    ),
                                }
                            )
                        )
                    elif risk.risk_id.endswith("compute-evidence"):
                        revised_risks.append(
                            risk.model_copy(
                                update={
                                    "description": (
                                        "The conservative 4x4 FxLMS stress case consumes "
                                        "the full credited accelerator allowance."
                                    ),
                                    "severity": ValidationSeverity.HIGH,
                                    "mitigation": (
                                        "Benchmark the final mapped 4x4 firmware before "
                                        "firmware closure."
                                    ),
                                }
                            )
                        )
                    else:
                        revised_risks.append(risk)
                architecture = direct.model_copy(
                    update={
                        "architecture_id": "system-adc-dsp-digital-class-d",
                        "name": "4-channel ADC + DSP + digital-input Class-D",
                        "topology": "adc_dsp_digital_class_d",
                        "functional_blocks": blocks,
                        "connections": connections,
                        "risks": revised_risks,
                        "evidence_ids": path_evidence,
                    }
                )
                codec = next(
                    (
                        candidate.candidate_id
                        for candidate in reversed(state.architecture_candidates)
                        if candidate.architecture.topology == "multichannel_codec"
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
                        "selected_candidate_id": direct_architecture.candidate_id,
                        "viable_alternative_ids": [],
                        "rejected_candidate_ids": [
                            item for item in (codec, integrated) if item is not None
                        ],
                        "rejection_reasons": [
                            "AD1938 and PCM3168A DAC outputs are analog and cannot feed the "
                            "selected TAS6424-Q1 digital audio input; retaining their DACs adds "
                            "latency and complexity without function.",
                            "No trusted candidate evidence establishes integrated DSP converter "
                            "capacity for four synchronized microphone inputs.",
                        ],
                        "evidence_ids": path_evidence,
                        "unresolved_trade_offs": [
                            "An analog-output amplifier alternative would require a new evidenced "
                            "part comparison and is not justified by the current "
                            "latency/complexity objective.",
                        ],
                    }
                )
        design_variables = classify_and_close_design_variables(
            state.master_spec, discovery.candidates
        )
        discovered_parts = {candidate.part_number for candidate in discovery.candidates}
        microphone_front_end = (
            build_microphone_front_end(discovery.candidates)
            if "ADAU1978" in discovered_parts
            else None
        )
        clock_tree = (
            build_clock_tree(discovery.candidates)
            if {"ADSP-21569", "ADAU1978", "TAS6424-Q1"} <= discovered_parts
            else None
        )
        power_tree = (
            build_power_tree(discovery.candidates)
            if {"ADSP-21569", "ADAU1978", "TAS6424-Q1", "ADP5054"} <= discovered_parts
            else None
        )
        computational_budget = (
            build_candidate_computational_budget(state.master_spec, dsp_candidate)
            if dsp_candidate is not None
            else state.computational_budget
        )
        readiness = assess_phase4_readiness(
            design_variables,
            discovery.candidates,
            microphone_front_end,
            clock_tree,
            power_tree,
            computational_budget,
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
                "computational_budget": computational_budget,
                "latency_budget": build_evidence_aware_latency_budget(discovery.candidates),
                "design_variables": design_variables,
                "microphone_front_end": microphone_front_end,
                "clock_tree": clock_tree,
                "power_tree": power_tree,
                "phase4_readiness": readiness,
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
