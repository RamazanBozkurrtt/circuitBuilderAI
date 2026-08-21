from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from ai_pcb.config import Settings
from ai_pcb.evidence.chunking import EngineeringChunker
from ai_pcb.evidence.embedding import FastEmbedProvider
from ai_pcb.evidence.errors import KnowledgeError
from ai_pcb.evidence.evaluation import evaluate_retrieval
from ai_pcb.evidence.ingestion import PdfDocumentIngestor
from ai_pcb.evidence.retrieval import QdrantHybridEvidenceIndex
from ai_pcb.evidence.store import EvidenceStore
from ai_pcb.models.knowledge import EngineeringEvidenceQuery, RetrievalEvaluationCase
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
        if name == "init":
            command.add_argument("--specialization", action="append", default=[])
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("path", nargs="?", type=Path)
    for name in ("search", "evidence-query"):
        search = subparsers.add_parser(name)
        search.add_argument("query")
        search.add_argument("--part-number")
        search.add_argument("--manufacturer")
        search.add_argument("--document-id")
        search.add_argument("--page", type=int, action="append", default=[])
        search.add_argument("--top-k", type=int, default=5)
        search.add_argument("--context", type=int, default=0)
    evaluation = subparsers.add_parser("retrieval-eval")
    evaluation.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path("knowledge/evaluation/synthetic_queries.json"),
    )
    return parser


def _knowledge_index(settings: Settings) -> QdrantHybridEvidenceIndex:
    return QdrantHybridEvidenceIndex(
        path=settings.ai_pcb_index_dir,
        ingestion_path=settings.ai_pcb_ingestion_dir,
        embedding_provider=FastEmbedProvider(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
            cache_dir=settings.embedding_cache_dir,
        ),
        collection_name=settings.retrieval_collection,
    )


def _ingestion_paths(path: Path | None, knowledge_root: Path) -> list[Path]:
    if path is not None:
        return sorted(path.rglob("*.pdf")) if path.is_dir() else [path]
    return sorted(
        pdf
        for directory in ("datasheets", "reference_designs", "app_notes")
        for pdf in (knowledge_root / directory).rglob("*.pdf")
    )


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = Settings()
    repository = ProjectRepository(Path(settings.ai_pcb_projects_dir))
    try:
        if arguments.command == "ingest":
            paths = _ingestion_paths(arguments.path, settings.ai_pcb_knowledge_dir)
            if not paths:
                raise ValueError("no PDF documents found for ingestion")
            ingestor = PdfDocumentIngestor(
                chunker=EngineeringChunker(
                    target_characters=settings.chunk_target_characters,
                    max_characters=settings.chunk_max_characters,
                ),
                ocr_minimum_characters=settings.ocr_minimum_characters,
            )
            index = _knowledge_index(settings)
            try:
                for path in paths:
                    print(index.index_document(ingestor.ingest(path)).model_dump_json(indent=2))
            finally:
                index.close()
            return 0
        if arguments.command in {"search", "evidence-query"}:
            query = EngineeringEvidenceQuery(
                query=arguments.query,
                manufacturer=arguments.manufacturer,
                part_number=arguments.part_number,
                document_id=arguments.document_id,
                pages=arguments.page,
                top_k=arguments.top_k,
                context_expansion=arguments.context,
            )
            index = _knowledge_index(settings)
            try:
                results = index.search(query)
            finally:
                index.close()
            if arguments.command == "evidence-query":
                print(json.dumps([item.model_dump(mode="json") for item in results], indent=2))
            else:
                for result in results:
                    preview = " ".join(result.extracted_text.split())[:180]
                    print(
                        f"{result.document_title} | page {result.page} | "
                        f"{result.section or '-'} | {result.scores.fused:.4f} | "
                        f"{result.retrieval_method.value}\n  {preview}"
                    )
            return 0
        if arguments.command == "retrieval-eval":
            raw_cases = json.loads(arguments.dataset.read_text(encoding="utf-8"))
            cases = [RetrievalEvaluationCase.model_validate(item) for item in raw_cases]
            index = _knowledge_index(settings)
            try:
                metrics = evaluate_retrieval(index, cases)
            finally:
                index.close()
            print(metrics.model_dump_json(indent=2))
            return 0
        if arguments.command == "init":
            state = repository.init(
                arguments.project_name,
                specializations=arguments.specialization or ["generic"],
            )
            location = repository.project_path(state.project_name)
            resolved = ", ".join(item.id for item in state.resolved_specializations)
            print(f"Initialized {state.project_name} at {location} ({resolved})")
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
    except (KnowledgeError, OSError, ProjectRepositoryError, ValidationError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
