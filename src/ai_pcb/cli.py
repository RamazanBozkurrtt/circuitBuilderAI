from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from ai_pcb.config import Settings
from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.state import WorkflowStage
from ai_pcb.persistence.project import ProjectRepository, ProjectRepositoryError
from ai_pcb.validation.engine import ValidationEngine
from ai_pcb.validation.references import EvidenceReferenceValidator
from ai_pcb.validation.spec import MasterSpecValidator
from ai_pcb.workflow.graph import Phase1Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-pcb")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "validate-spec", "run", "show-state"):
        command = subparsers.add_parser(name)
        command.add_argument("project_name")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = Settings()
    repository = ProjectRepository(Path(settings.ai_pcb_projects_dir))
    try:
        if arguments.command == "init":
            state = repository.init(arguments.project_name)
            location = repository.project_path(state.project_name)
            print(f"Initialized {state.project_name} at {location}")
            return 0
        if arguments.command == "show-state":
            print(repository.load_state(arguments.project_name).model_dump_json(indent=2))
            return 0
        if arguments.command == "validate-spec":
            state = repository.load_state(arguments.project_name)
            store = EvidenceStore(repository.project_path(arguments.project_name) / "evidence")
            report = ValidationEngine(
                [MasterSpecValidator(), EvidenceReferenceValidator(store)]
            ).run(
                state,
                report_id=f"spec-cli-{state.iteration:03d}",
                stage="SPECIFICATION",
            )
            print(report.model_dump_json(indent=2))
            return 0 if report.can_advance else 2
        if arguments.command == "run":
            state = repository.load_state(arguments.project_name)
            if state.workflow_stage is WorkflowStage.BLOCKED:
                from ai_pcb.workflow.transitions import transition_state

                state = transition_state(
                    state,
                    WorkflowStage.SPECIFICATION,
                    "manual rerun after project inputs changed",
                    require_verification=False,
                )
            state = state.model_copy(update={"iteration": state.iteration + 1})
            final_state = Phase1Workflow(
                max_iterations=settings.max_design_iterations,
                evidence_store=EvidenceStore(
                    repository.project_path(arguments.project_name) / "evidence"
                ),
                checkpoint=repository.checkpoint_current,
            ).invoke(state)
            repository.persist_iteration(final_state)
            print(final_state.model_dump_json(indent=2))
            return 0 if final_state.workflow_stage.value == "COMPLETE" else 2
    except (ProjectRepositoryError, ValidationError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
