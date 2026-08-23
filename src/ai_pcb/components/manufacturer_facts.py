from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf
import yaml

from ai_pcb.evidence.acquisition import evidence_source_for
from ai_pcb.evidence.store import EvidenceNotFoundError, EvidenceStore
from ai_pcb.models.acquisition import (
    AcquisitionCatalog,
    AcquisitionResult,
    AcquisitionVerificationStatus,
)
from ai_pcb.models.architecture import EngineeringValue, ValueStatus
from ai_pcb.models.components import (
    CandidateEvidenceStatus,
    ComponentCandidate,
    ComponentFact,
    ManufacturerComponentFact,
    ManufacturerComponentFactCatalog,
)
from ai_pcb.models.evidence import Evidence, EvidenceProvenance


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


class TrustedManufacturerFactRepository:
    """Validates curated facts against immutable trusted PDFs before exposing candidates."""

    def __init__(
        self,
        *,
        fact_catalog_path: Path,
        acquisition_catalog_path: Path,
        evidence_store: EvidenceStore,
    ) -> None:
        raw = yaml.safe_load(fact_catalog_path.read_text(encoding="utf-8"))
        self.fact_catalog = ManufacturerComponentFactCatalog.model_validate_json(
            json.dumps(raw)
        )
        self.acquisition_catalog = AcquisitionCatalog.model_validate_json(
            acquisition_catalog_path.read_text(encoding="utf-8")
        )
        self.evidence_store = evidence_store

    def candidates(self) -> list[ComponentCandidate]:
        acquisitions = {
            item.acquisition_id: item for item in self.acquisition_catalog.documents
        }
        grouped: dict[tuple[object, str, str], list[ManufacturerComponentFact]] = {}
        for fact in self.fact_catalog.facts:
            acquisition = acquisitions.get(fact.acquisition_id)
            self._validate_fact(fact, acquisition)
            assert acquisition is not None
            self._promote_fact(fact, acquisition)
            key = (
                fact.candidate_category,
                fact.candidate_manufacturer,
                fact.candidate_part_number,
            )
            grouped.setdefault(key, []).append(fact)
        candidates: list[ComponentCandidate] = []
        for (_raw_category, manufacturer, part_number), facts in grouped.items():
            category = facts[0].candidate_category
            digest = hashlib.sha256(
                f"{category.value}:{manufacturer}:{part_number}".encode()
            ).hexdigest()[:12]
            acquisitions_for_candidate = list(
                dict.fromkeys(fact.acquisition_id for fact in facts)
            )
            candidates.append(
                ComponentCandidate(
                    candidate_id=f"candidate-{digest}",
                    category=category,
                    manufacturer=manufacturer,
                    part_number=part_number,
                    evidence_status=CandidateEvidenceStatus.EVIDENCE_VERIFIED,
                    identity_source_ids=acquisitions_for_candidate,
                    verified_evidence_ids=[fact.fact_id for fact in facts],
                    facts=[
                        ComponentFact(
                            attribute=fact.attribute,
                            value=EngineeringValue(
                                status=ValueStatus.KNOWN,
                                value=fact.value,
                                unit=fact.unit,
                                conditions=fact.conditions,
                                evidence_ids=[fact.fact_id],
                            ),
                        )
                        for fact in facts
                    ],
                )
            )
        return candidates

    @staticmethod
    def _validate_fact(
        fact: ManufacturerComponentFact, acquisition: AcquisitionResult | None
    ) -> None:
        if acquisition is None:
            raise ValueError(f"fact references unknown acquisition: {fact.fact_id}")
        if acquisition.verification_status is not AcquisitionVerificationStatus.TRUSTED:
            raise ValueError(f"fact references untrusted acquisition: {fact.fact_id}")
        if acquisition.sha256 != fact.document_sha256:
            raise ValueError(f"fact document hash mismatch: {fact.fact_id}")
        if acquisition.manufacturer != fact.candidate_manufacturer:
            raise ValueError(f"fact manufacturer mismatch: {fact.fact_id}")
        path = Path(acquisition.local_path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != fact.document_sha256:
            raise ValueError(f"immutable source bytes changed for fact: {fact.fact_id}")
        document = pymupdf.open(path)  # type: ignore[no-untyped-call]
        try:
            if fact.page > document.page_count:
                raise ValueError(f"fact page is outside the source PDF: {fact.fact_id}")
            page_text = document.load_page(fact.page - 1).get_text()  # type: ignore[no-untyped-call]
        finally:
            document.close()  # type: ignore[no-untyped-call]
        if _normalized_text(fact.evidence_text) not in _normalized_text(page_text):
            raise ValueError(f"fact evidence text is absent from source page: {fact.fact_id}")

    def _promote_fact(
        self, fact: ManufacturerComponentFact, acquisition: AcquisitionResult
    ) -> None:
        evidence = Evidence(
            evidence_id=fact.fact_id,
            title=f"{fact.candidate_part_number} {fact.attribute}",
            provenance=EvidenceProvenance(
                source=evidence_source_for(acquisition.document_type),
                manufacturer=acquisition.manufacturer,
                document=Path(acquisition.local_path).name,
                page=str(fact.page),
                locator=f"page={fact.page}",
                source_url=acquisition.final_url,
                sha256=acquisition.sha256,
                acquisition_id=acquisition.acquisition_id,
            ),
            extracted_content=fact.evidence_text,
            normalized_fact=fact.normalized_fact,
            artifact_path=acquisition.local_path,
        )
        try:
            existing = self.evidence_store.get(evidence.evidence_id)
        except EvidenceNotFoundError:
            self.evidence_store.add(evidence)
            return
        if existing.normalized_fact != evidence.normalized_fact:
            raise ValueError(f"promoted fact changed without a new evidence ID: {fact.fact_id}")
