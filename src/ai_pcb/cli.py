from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from ai_pcb.architecture.reporting import render_phase3_report
from ai_pcb.components.discovery import EvidenceGroundedCandidateDiscovery
from ai_pcb.components.manufacturer_facts import TrustedManufacturerFactRepository
from ai_pcb.config import Settings
from ai_pcb.evidence.acquisition import (
    HttpManufacturerDocumentationProvider,
    ManufacturerEvidenceAcquisitionPipeline,
    load_acquisition_manifest,
)
from ai_pcb.evidence.chunking import EngineeringChunker
from ai_pcb.evidence.embedding import FastEmbedProvider
from ai_pcb.evidence.errors import KnowledgeError
from ai_pcb.evidence.evaluation import evaluate_retrieval_corpora
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
from ai_pcb.workflow.phase3 import Phase3Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-pcb")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "init",
        "validate-spec",
        "run",
        "show-state",
        "architecture",
        "component-candidates",
        "component-report",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("project_name")
        if name == "init":
            command.add_argument("--specialization", action="append", default=[])
        if name in {"architecture", "component-candidates", "component-report"}:
            command.add_argument("--refresh-evidence", action="store_true")
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
    evaluation.add_argument(
        "--real-dataset",
        type=Path,
        default=Path("knowledge/evaluation/real_datasheet_queries.json"),
    )
    acquisition = subparsers.add_parser("acquire-documents")
    acquisition.add_argument("manifest", type=Path)
    acquisition.add_argument("--ingest", action="store_true")
    return parser


def _knowledge_index(settings: Settings) -> QdrantHybridEvidenceIndex:
    return QdrantHybridEvidenceIndex(
        path=settings.ai_pcb_index_dir,
        ingestion_path=settings.ai_pcb_ingestion_dir,
        embedding_provider=FastEmbedProvider(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
            cache_dir=settings.embedding_cache_dir,
            batch_size=settings.embedding_batch_size,
        ),
        collection_name=settings.retrieval_collection,
    )


def _ingestion_paths(path: Path | None, knowledge_root: Path) -> list[Path]:
    if path is not None:
        return sorted(path.rglob("*.pdf")) if path.is_dir() else [path]
    return sorted(
        pdf
        for directory in ("datasheets", "reference_designs", "app_notes", "errata")
        for pdf in (knowledge_root / directory).rglob("*.pdf")
    )


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = Settings()
    repository = ProjectRepository(Path(settings.ai_pcb_projects_dir))
    try:
        if arguments.command == "acquire-documents":
            manifest = load_acquisition_manifest(arguments.manifest)
            provider = HttpManufacturerDocumentationProvider(
                knowledge_root=settings.ai_pcb_knowledge_dir,
                trusted_domains=settings.trusted_manufacturer_domains,
                timeout_seconds=settings.acquisition_timeout_seconds,
                max_redirects=settings.acquisition_max_redirects,
            )
            index: QdrantHybridEvidenceIndex | None = None
            ingestor: PdfDocumentIngestor | None = None
            if arguments.ingest:
                ingestor = PdfDocumentIngestor(
                    chunker=EngineeringChunker(
                        target_characters=settings.chunk_target_characters,
                        max_characters=settings.chunk_max_characters,
                    ),
                    ocr_minimum_characters=settings.ocr_minimum_characters,
                )
                index = _knowledge_index(settings)
            try:
                acquisition_result = ManufacturerEvidenceAcquisitionPipeline(
                    provider,
                    ingestor=ingestor,
                    indexer=index,
                ).acquire_manifest(manifest)
            finally:
                if index is not None:
                    index.close()
            print(acquisition_result.model_dump_json(indent=2))
            return 0 if not acquisition_result.failed else 2
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
            raw_real_cases = json.loads(arguments.real_dataset.read_text(encoding="utf-8"))
            real_cases = [
                RetrievalEvaluationCase.model_validate(item) for item in raw_real_cases
            ]
            index = _knowledge_index(settings)
            try:
                metrics = evaluate_retrieval_corpora(
                    index,
                    synthetic_cases=cases,
                    real_datasheet_cases=real_cases,
                )
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
        if arguments.command in {
            "architecture",
            "component-candidates",
            "component-report",
        }:
            state = repository.load_state(arguments.project_name)
            phase3_index: QdrantHybridEvidenceIndex | None = None
            registry_path = settings.ai_pcb_ingestion_dir / "registry.json"
            fact_catalog = (
                repository.project_path(state.project_name)
                / "manufacturer_component_facts.yaml"
            )
            acquisition_catalog = (
                settings.ai_pcb_knowledge_dir / "acquisition_metadata" / "catalog.json"
            )
            fact_repository = (
                TrustedManufacturerFactRepository(
                    fact_catalog_path=fact_catalog,
                    acquisition_catalog_path=acquisition_catalog,
                    evidence_store=EvidenceStore(
                        repository.project_path(state.project_name) / "evidence"
                    ),
                )
                if fact_catalog.is_file() and acquisition_catalog.is_file()
                else None
            )
            discovery = EvidenceGroundedCandidateDiscovery(None, fact_repository)
            if registry_path.is_file():
                phase3_index = _knowledge_index(settings)
                discovery = EvidenceGroundedCandidateDiscovery(
                    phase3_index, fact_repository
                )
            try:
                if arguments.refresh_evidence or not state.phase3_complete:
                    state = Phase3Workflow(
                        max_iterations=max(1, settings.max_design_iterations),
                        candidate_discovery=discovery,
                        checkpoint=repository.checkpoint_current,
                    ).invoke(state)
                    repository.save_current(state)
            finally:
                if phase3_index is not None:
                    phase3_index.close()
            if arguments.command == "architecture":
                if state.architecture is None:
                    raise ValueError("Phase 3 produced no architecture")
                print(state.architecture.model_dump_json(indent=2))
            elif arguments.command == "component-candidates":
                print(
                    json.dumps(
                        {
                            "candidates": [
                                item.model_dump(mode="json") for item in state.component_candidates
                            ],
                            "evidence_acquisition_requirements": [
                                item.model_dump(mode="json")
                                for item in state.evidence_acquisition_requirements
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                phase3_report_text = render_phase3_report(state)
                output = repository.project_path(state.project_name) / "outputs" / "phase3.txt"
                output.write_text(phase3_report_text, encoding="utf-8", newline="\n")
                print(phase3_report_text, end="")
            return 0 if state.phase3_complete else 2
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
