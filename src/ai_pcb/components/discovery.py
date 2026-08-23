from __future__ import annotations

import hashlib

from pydantic import Field

from ai_pcb.components.manufacturer_facts import TrustedManufacturerFactRepository
from ai_pcb.evidence.retrieval import EvidenceRetriever
from ai_pcb.models.acquisition import AcquisitionVerificationStatus
from ai_pcb.models.common import StrictModel
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    ComponentCandidate,
    ComponentCategory,
    ComponentRequirement,
    EvidenceAcquisitionRequirement,
)
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import EngineeringEvidenceQuery
from ai_pcb.specializations.models import ResolvedSpecializationContext


class CandidateDiscoveryResult(StrictModel):
    candidates: list[ComponentCandidate] = Field(default_factory=list)
    evidence_requirements: list[EvidenceAcquisitionRequirement] = Field(default_factory=list)


class EvidenceGroundedCandidateDiscovery:
    def __init__(
        self,
        retriever: EvidenceRetriever | None,
        fact_repository: TrustedManufacturerFactRepository | None = None,
    ) -> None:
        self.retriever = retriever
        self.fact_repository = fact_repository

    def discover(
        self,
        requirements: list[ComponentRequirement],
        context: ResolvedSpecializationContext,
    ) -> CandidateDiscoveryResult:
        by_category: dict[ComponentCategory, list[ComponentRequirement]] = {}
        for requirement in requirements:
            by_category.setdefault(requirement.category, []).append(requirement)
        candidates = self.fact_repository.candidates() if self.fact_repository else []
        acquisitions: list[EvidenceAcquisitionRequirement] = []
        guidance_by_category = {
            ComponentCategory(item.category): item for item in context.component_categories
        }
        for category, category_requirements in by_category.items():
            guidance = guidance_by_category[category]
            retrieved = []
            if self.retriever is not None and self.fact_repository is None:
                query_text = " ".join(
                    dict.fromkeys(
                        [
                            category.value.replace("_", " "),
                            *guidance.retrieval_hints,
                            *context.retrieval_hints,
                        ]
                    )
                )
                retrieved = self.retriever.search(
                    EngineeringEvidenceQuery(
                        query=query_text,
                        source_types=[
                            EvidenceSource.DATASHEET,
                            EvidenceSource.REFERENCE_DESIGN,
                            EvidenceSource.APPLICATION_NOTE,
                        ],
                        top_k=20,
                    )
                )
            grouped: dict[tuple[str, str], list[str]] = {}
            for result in retrieved:
                if (
                    not result.part_number
                    or not result.manufacturer
                    or result.acquisition is None
                    or result.acquisition.verification_status
                    is not AcquisitionVerificationStatus.TRUSTED
                ):
                    continue
                grouped.setdefault((result.manufacturer, result.part_number), []).append(
                    result.evidence_candidate_id
                )
            for (manufacturer, part_number), source_ids in grouped.items():
                existing = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.category is category
                        and candidate.manufacturer == manufacturer
                        and candidate.part_number == part_number
                    ),
                    None,
                )
                if existing is not None:
                    continue
                digest = hashlib.sha256(
                    f"{category.value}:{manufacturer}:{part_number}".encode()
                ).hexdigest()[:12]
                candidates.append(
                    ComponentCandidate(
                        candidate_id=f"candidate-{digest}",
                        category=category,
                        manufacturer=manufacturer,
                        part_number=part_number,
                        evidence_status=CandidateEvidenceStatus.IDENTITY_KNOWN,
                        identity_source_ids=list(dict.fromkeys(source_ids)),
                    )
                )
            if not any(candidate.category is category for candidate in candidates):
                acquisitions.append(
                    EvidenceAcquisitionRequirement(
                        requirement_id=f"evidence-{category.value.lower()}",
                        category=category,
                        required_facts=[item.attribute for item in category_requirements],
                        preferred_source_types=[
                            source
                            for evidence_requirement in context.evidence_requirements
                            for source in evidence_requirement.preferred_source_types
                        ]
                        or ["DATASHEET"],
                        reason=(
                            "No retrieved manufacturer source establishes a candidate identity "
                            "and the facts required for evaluation."
                        ),
                    )
                )
        return CandidateDiscoveryResult(candidates=candidates, evidence_requirements=acquisitions)
