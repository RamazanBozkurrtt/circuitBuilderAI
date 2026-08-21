from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel
from ai_pcb.models.evidence import EvidenceSource


class ExtractionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    REQUIRES_OCR = "REQUIRES_OCR"


class BlockKind(StrEnum):
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    LIST = "LIST"


class ChunkKind(StrEnum):
    TEXT = "TEXT"
    TABLE = "TABLE"


class RetrievalMethod(StrEnum):
    DENSE = "DENSE"
    LEXICAL = "LEXICAL"
    HYBRID = "HYBRID"


class FactStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class BoundingBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered(self) -> BoundingBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box coordinates are not ordered")
        return self

    def locator(self) -> str:
        return f"bbox({self.x0:.2f},{self.y0:.2f},{self.x1:.2f},{self.y1:.2f})"


class DocumentMetadata(StrictModel):
    document_id: Identifier
    source_file: NonEmptyString
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: EvidenceSource
    manufacturer: str | None = None
    part_number: str | None = None
    title: NonEmptyString
    revision: str | None = None
    total_pages: int = Field(ge=1)

    @model_validator(mode="after")
    def local_document_source(self) -> DocumentMetadata:
        allowed = {
            EvidenceSource.DATASHEET,
            EvidenceSource.REFERENCE_DESIGN,
            EvidenceSource.APPLICATION_NOTE,
        }
        if self.source_type not in allowed:
            raise ValueError("knowledge documents require a supported local document source type")
        return self


class DocumentBlock(StrictModel):
    block_id: Identifier
    page: int = Field(ge=1)
    reading_order: int = Field(ge=0)
    kind: BlockKind
    text: NonEmptyString
    section: str | None = None
    bbox: BoundingBox | None = None


class DocumentTable(StrictModel):
    table_id: Identifier
    page: int = Field(ge=1)
    reading_order: int = Field(ge=0)
    headers: list[str]
    rows: list[list[str]]
    section: str | None = None
    bbox: BoundingBox | None = None

    @model_validator(mode="after")
    def consistent_width(self) -> DocumentTable:
        width = len(self.headers)
        if width == 0:
            raise ValueError("a table must have at least one column")
        if any(len(row) != width for row in self.rows):
            raise ValueError("table rows must match header width")
        return self

    def as_text(self) -> str:
        lines = [" | ".join(self.headers)]
        lines.extend(" | ".join(row) for row in self.rows)
        return "\n".join(lines)


class DocumentSection(StrictModel):
    section_id: Identifier
    title: NonEmptyString
    page: int = Field(ge=1)
    heading_block_id: Identifier


class DocumentPage(StrictModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    extraction_status: ExtractionStatus
    machine_readable_characters: int = Field(ge=0)
    image_count: int = Field(default=0, ge=0)
    blocks: list[DocumentBlock] = Field(default_factory=list)
    tables: list[DocumentTable] = Field(default_factory=list)
    section_ids: list[Identifier] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def child_pages_match(self) -> DocumentPage:
        if any(block.page != self.page_number for block in self.blocks):
            raise ValueError("document block page does not match its containing page")
        if any(table.page != self.page_number for table in self.tables):
            raise ValueError("document table page does not match its containing page")
        return self


class DocumentChunk(StrictModel):
    chunk_id: Identifier
    document_id: Identifier
    source_file: NonEmptyString
    document_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: EvidenceSource
    manufacturer: str | None = None
    part_number: str | None = None
    document_title: NonEmptyString
    document_revision: str | None = None
    page: int = Field(ge=1)
    section: str | None = None
    kind: ChunkKind
    text: NonEmptyString
    block_ids: list[Identifier] = Field(default_factory=list)
    table_ids: list[Identifier] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    locator: NonEmptyString
    previous_chunk_id: Identifier | None = None
    next_chunk_id: Identifier | None = None


class DocumentRecord(StrictModel):
    metadata: DocumentMetadata
    pages: list[DocumentPage]
    sections: list[DocumentSection]
    chunks: list[DocumentChunk]

    @model_validator(mode="after")
    def complete_pages(self) -> DocumentRecord:
        expected = list(range(1, self.metadata.total_pages + 1))
        if [page.page_number for page in self.pages] != expected:
            raise ValueError("document pages must be complete and ordered")
        if len({chunk.chunk_id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("document contains duplicate chunk identifiers")
        for chunk in self.chunks:
            if (
                chunk.document_id != self.metadata.document_id
                or chunk.document_hash != self.metadata.sha256
                or chunk.source_file != self.metadata.source_file
                or chunk.source_type is not self.metadata.source_type
            ):
                raise ValueError("chunk provenance is inconsistent with document metadata")
        return self


class IngestionIssue(StrictModel):
    page: int | None = Field(default=None, ge=1)
    code: NonEmptyString
    message: NonEmptyString


class IngestionReport(StrictModel):
    document_id: Identifier
    source_file: NonEmptyString
    document_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_document_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pages_processed: int = Field(ge=0)
    chunks_created: int = Field(ge=0)
    requires_ocr_pages: list[int] = Field(default_factory=list)
    issues: list[IngestionIssue] = Field(default_factory=list)
    unchanged: bool = False


class EngineeringEvidenceQuery(StrictModel):
    query: NonEmptyString
    source_types: list[EvidenceSource] = Field(default_factory=list)
    manufacturer: str | None = None
    part_number: str | None = None
    document_id: Identifier | None = None
    section_preference: str | None = None
    pages: list[int] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=100)
    context_expansion: int = Field(default=0, ge=0, le=3)
    minimum_retrieval_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrievalScores(StrictModel):
    dense: float | None = None
    lexical: float | None = None
    fused: float = Field(ge=0.0, le=1.0)


class EvidenceContextPiece(StrictModel):
    chunk_id: Identifier
    document_id: Identifier
    source_file: NonEmptyString
    document_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: EvidenceSource
    page: int = Field(ge=1)
    section: str | None = None
    locator: NonEmptyString
    text: NonEmptyString


class EngineeringEvidenceCandidate(StrictModel):
    evidence_candidate_id: Identifier
    chunk_id: Identifier
    document_id: Identifier
    source_file: NonEmptyString
    source_type: EvidenceSource
    manufacturer: str | None = None
    part_number: str | None = None
    document_title: NonEmptyString
    document_revision: str | None = None
    document_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    section: str | None = None
    locator: NonEmptyString
    extracted_text: NonEmptyString
    scores: RetrievalScores
    retrieval_method: RetrievalMethod
    context: list[EvidenceContextPiece] = Field(default_factory=list)


class FactConflict(StrictModel):
    description: NonEmptyString
    evidence_ids: list[Identifier] = Field(min_length=1)


class EngineeringFactCandidate(StrictModel):
    fact_type: str | None = None
    subject: str | None = None
    value: str | None = None
    unit: str | None = None
    conditions: list[str] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    conflicts: list[FactConflict] = Field(default_factory=list)
    status: FactStatus

    @model_validator(mode="after")
    def fail_closed_semantics(self) -> EngineeringFactCandidate:
        if self.status is FactStatus.EXTRACTED:
            if not self.value or not self.evidence_ids:
                raise ValueError("an extracted fact requires a value and evidence_ids")
        elif self.status is FactStatus.INSUFFICIENT_EVIDENCE:
            if self.value is not None or self.evidence_ids:
                raise ValueError("insufficient evidence cannot contain a claimed fact")
        elif self.status is FactStatus.CONFLICTING_EVIDENCE:
            if self.value is not None:
                raise ValueError("conflicting evidence cannot select a value")
            if not self.conflicts or len(self.evidence_ids) < 2:
                raise ValueError(
                    "conflicting evidence requires conflicts and at least two evidence_ids"
                )
        return self


class RetrievalEvaluationCase(StrictModel):
    case_id: Identifier
    query: EngineeringEvidenceQuery
    expected_document_id: Identifier
    expected_page: int | None = Field(default=None, ge=1)
    expected_chunk_id: Identifier | None = None


class RetrievalEvaluationMetrics(StrictModel):
    cases: int = Field(ge=0)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(ge=0.0, le=1.0)
