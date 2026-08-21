from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.state import DesignState, WorkflowStage
from ai_pcb.models.validation import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    VerificationReport,
)
from ai_pcb.validation.engine import ValidationEngine
from ai_pcb.validation.references import (
    EvidenceReferenceValidator,
    EvidenceValidationUnavailable,
)
from ai_pcb.validation.spec import MasterSpecValidator
from ai_pcb.workflow.transitions import transition_state

StageHandler = Callable[[DesignState], VerificationReport]
StateCheckpoint = Callable[[DesignState], None]


class WorkflowContext(TypedDict):
    design_state: DesignState
    route: str
    correction_target: str


_STAGE_BY_NODE: dict[str, WorkflowStage] = {
    "architecture": WorkflowStage.ARCHITECTURE,
    "component_selection": WorkflowStage.COMPONENT_SELECTION,
    "datasheet_analysis": WorkflowStage.DATASHEET_ANALYSIS,
    "schematic_design": WorkflowStage.SCHEMATIC,
    "schematic_validation": WorkflowStage.SCHEMATIC_VERIFICATION,
    "pcb_layout": WorkflowStage.PCB_LAYOUT,
    "pcb_validation": WorkflowStage.PCB_VERIFICATION,
    "manufacturing": WorkflowStage.MANUFACTURING,
    "final_review": WorkflowStage.MANUFACTURING,
}

_NEXT_NODE: dict[str, str] = {
    "architecture": "component_selection",
    "component_selection": "datasheet_analysis",
    "datasheet_analysis": "schematic_design",
    "schematic_design": "schematic_validation",
    "schematic_validation": "pcb_layout",
    "pcb_layout": "pcb_validation",
    "pcb_validation": "manufacturing",
    "manufacturing": "final_review",
    "final_review": "complete",
}

_CORRECTION_TARGET: dict[str, str] = {
    "schematic_validation": "schematic_design",
    "pcb_validation": "pcb_layout",
    "final_review": "manufacturing",
}


class Phase1Workflow:
    """Real LangGraph routing with fail-closed Phase 1 placeholder stages."""

    def __init__(
        self,
        *,
        max_iterations: int,
        stage_handlers: dict[str, StageHandler] | None = None,
        evidence_store: EvidenceStore | None = None,
        checkpoint: StateCheckpoint | None = None,
    ) -> None:
        if max_iterations < 0:
            raise ValueError("max_iterations cannot be negative")
        self.max_iterations = max_iterations
        self.stage_handlers = stage_handlers or {}
        self.evidence_store = evidence_store
        self.checkpoint = checkpoint
        self.graph = self._build_graph()

    def invoke(self, state: DesignState) -> DesignState:
        result = self.graph.invoke(
            {"design_state": state, "route": "load_spec", "correction_target": ""}
        )
        return DesignState.model_validate(result["design_state"])

    def _build_graph(self) -> Any:
        builder = StateGraph(WorkflowContext)
        builder.add_node("load_spec", self._load_spec)  # type: ignore[call-overload]
        builder.add_node("validate_spec", self._validate_spec)  # type: ignore[call-overload]
        for node_name in _STAGE_BY_NODE:
            # LangGraph's overload does not accept its own callable shape under strict mypy.
            builder.add_node(  # type: ignore[call-overload]
                node_name, self._make_stage_node(node_name)
            )
        builder.add_node("correction", self._correction)  # type: ignore[call-overload]
        builder.add_node("blocked", self._blocked)  # type: ignore[call-overload]

        builder.add_edge(START, "load_spec")
        builder.add_edge("load_spec", "validate_spec")
        builder.add_conditional_edges(
            "validate_spec", self._route, {"architecture": "architecture", "blocked": "blocked"}
        )
        for node_name in _STAGE_BY_NODE:
            possible: dict[Hashable, str] = {"blocked": "blocked"}
            next_node = _NEXT_NODE[node_name]
            if next_node == "complete":
                possible["complete"] = END
            else:
                possible[next_node] = next_node
            if node_name in _CORRECTION_TARGET:
                possible["correction"] = "correction"
            builder.add_conditional_edges(node_name, self._route, possible)
        builder.add_conditional_edges(
            "correction",
            self._route,
            {
                "schematic_design": "schematic_design",
                "pcb_layout": "pcb_layout",
                "manufacturing": "manufacturing",
                "blocked": "blocked",
            },
        )
        builder.add_edge("blocked", END)
        return builder.compile()

    @staticmethod
    def _route(context: WorkflowContext) -> str:
        return context["route"]

    @staticmethod
    def _load_spec(context: WorkflowContext) -> WorkflowContext:
        # Repository loading happens before graph invocation; this node makes that routing explicit.
        return {**context, "route": "validate_spec"}

    def _validate_spec(self, context: WorkflowContext) -> WorkflowContext:
        state = context["design_state"]
        evidence_validator = (
            EvidenceReferenceValidator(self.evidence_store)
            if self.evidence_store is not None
            else EvidenceValidationUnavailable()
        )
        report = ValidationEngine([MasterSpecValidator(), evidence_validator]).run(
            state, report_id=f"spec-iteration-{state.iteration:03d}", stage="SPECIFICATION"
        )
        updated = state.model_copy(
            update={"verification_reports": [*state.verification_reports, report]}
        )
        self._checkpoint(updated)
        if report.can_advance:
            return {**context, "design_state": updated, "route": "architecture"}
        return {
            **context,
            "design_state": updated,
            "route": "blocked",
            "correction_target": "",
        }

    def _make_stage_node(
        self, node_name: str
    ) -> Callable[[WorkflowContext], WorkflowContext]:
        def run(context: WorkflowContext) -> WorkflowContext:
            state = self._enter_stage(context["design_state"], node_name)
            handler = self.stage_handlers.get(node_name)
            report = handler(state) if handler is not None else self._unavailable(node_name)
            updated = state.model_copy(
                update={"verification_reports": [*state.verification_reports, report]}
            )
            self._checkpoint(updated)
            if report.can_advance:
                if node_name == "final_review":
                    updated = transition_state(
                        updated, WorkflowStage.COMPLETE, "final review passed"
                    )
                return {**context, "design_state": updated, "route": _NEXT_NODE[node_name]}
            if node_name in _CORRECTION_TARGET and handler is not None:
                return {
                    **context,
                    "design_state": updated,
                    "route": "correction",
                    "correction_target": _CORRECTION_TARGET[node_name],
                }
            blockers = [*updated.blockers, f"{node_name} did not produce passing verification"]
            blocked_state = updated.model_copy(update={"blockers": blockers})
            self._checkpoint(blocked_state)
            return {
                **context,
                "design_state": blocked_state,
                "route": "blocked",
            }

        return run

    @staticmethod
    def _unavailable(node_name: str) -> VerificationReport:
        result = ValidationResult(
            result_id=f"{node_name}-unavailable",
            validator="phase1_availability",
            status=ValidationStatus.UNKNOWN,
            severity=ValidationSeverity.CRITICAL,
            summary=f"{node_name} is unavailable in Phase 1",
            details=["No engineering verification was performed."],
        )
        return VerificationReport(
            report_id=f"{node_name}-unavailable",
            stage=node_name,
            results=[result],
            can_advance=False,
        )

    @staticmethod
    def _enter_stage(state: DesignState, node_name: str) -> DesignState:
        target = _STAGE_BY_NODE[node_name]
        if state.workflow_stage is target:
            return state
        return transition_state(state, target, f"entered workflow node {node_name}")

    def _correction(self, context: WorkflowContext) -> WorkflowContext:
        state = context["design_state"]
        if state.iteration >= self.max_iterations:
            blockers = [
                *state.blockers,
                f"maximum design iterations reached ({self.max_iterations})",
            ]
            blocked_state = state.model_copy(update={"blockers": blockers})
            self._checkpoint(blocked_state)
            return {
                **context,
                "design_state": blocked_state,
                "route": "blocked",
            }
        target_node = context["correction_target"]
        target_stage = _STAGE_BY_NODE[target_node]
        incremented = state.model_copy(update={"iteration": state.iteration + 1})
        corrected = transition_state(
            incremented,
            target_stage,
            f"correction requested after failed verification; retrying {target_node}",
            require_verification=False,
        )
        self._checkpoint(corrected)
        return {**context, "design_state": corrected, "route": target_node}

    def _blocked(self, context: WorkflowContext) -> WorkflowContext:
        state = context["design_state"]
        if state.workflow_stage is WorkflowStage.BLOCKED:
            self._checkpoint(state)
            return {**context, "design_state": state, "route": "blocked"}
        blocked_state = transition_state(
            state,
            WorkflowStage.BLOCKED,
            state.blockers[-1] if state.blockers else "critical validation blocked progression",
            require_verification=False,
        )
        self._checkpoint(blocked_state)
        return {
            **context,
            "design_state": blocked_state,
            "route": "blocked",
        }

    def _checkpoint(self, state: DesignState) -> None:
        if self.checkpoint is not None:
            self.checkpoint(state)
