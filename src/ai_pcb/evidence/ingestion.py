from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pymupdf

from ai_pcb.evidence.chunking import EngineeringChunker
from ai_pcb.evidence.errors import (
    DocumentExtractionError,
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import (
    BlockKind,
    BoundingBox,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    DocumentRecord,
    DocumentSection,
    DocumentTable,
    ExtractionStatus,
)

_REVISION = re.compile(r"\b(?:rev(?:ision)?\.?|document revision)\s*[:#-]?\s*([A-Z0-9.-]+)", re.I)
_PART_NUMBER = re.compile(r"\b[A-Z]{2,}[A-Z0-9-]*\d[A-Z0-9-]*\b")


def _stable_id(prefix: str, material: str) -> str:
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _bbox(raw: object) -> BoundingBox | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    values = [float(value) for value in raw]
    return BoundingBox(x0=values[0], y0=values[1], x1=values[2], y1=values[3])


def _source_type(path: Path) -> EvidenceSource:
    directory_names = {part.lower() for part in path.parts}
    if "datasheets" in directory_names:
        return EvidenceSource.DATASHEET
    if "reference_designs" in directory_names:
        return EvidenceSource.REFERENCE_DESIGN
    if "app_notes" in directory_names:
        return EvidenceSource.APPLICATION_NOTE
    raise UnsupportedDocumentError(
        "document type is unknown; place the PDF under datasheets, reference_designs, or app_notes"
    )


class PdfDocumentIngestor:
    def __init__(
        self,
        *,
        chunker: EngineeringChunker | None = None,
        ocr_minimum_characters: int = 40,
    ) -> None:
        self.chunker = chunker or EngineeringChunker()
        self.ocr_minimum_characters = ocr_minimum_characters

    def ingest(
        self,
        path: Path,
        *,
        source_type: EvidenceSource | None = None,
        manufacturer: str | None = None,
        part_number: str | None = None,
    ) -> DocumentRecord:
        path = path.resolve()
        if path.suffix.lower() != ".pdf":
            raise UnsupportedDocumentError(f"unsupported document: {path}")
        if not path.is_file():
            raise UnsupportedDocumentError(f"document does not exist: {path}")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        try:
            document = pymupdf.open(path)  # type: ignore[no-untyped-call]
        except Exception as exc:
            raise DocumentExtractionError(f"cannot open PDF: {path}") from exc
        try:
            if document.page_count == 0:
                raise EmptyDocumentError(f"PDF contains no pages: {path}")
            raw_metadata = dict(document.metadata or {})
            pages, sections = self._extract_pages(document, digest)
            if not any(page.blocks or page.tables or page.image_count for page in pages):
                raise EmptyDocumentError(f"PDF contains no extractable content: {path}")
            first_text = "\n".join(block.text for page in pages[:2] for block in page.blocks)
            title = str(raw_metadata.get("title") or "").strip() or path.stem
            revision = self._first_match(_REVISION, first_text)
            detected_part = self._detect_part_number(path.stem, first_text)
            metadata = DocumentMetadata(
                document_id=_stable_id("doc", digest),
                source_file=str(path),
                sha256=digest,
                source_type=source_type or _source_type(path),
                manufacturer=manufacturer or str(raw_metadata.get("author") or "").strip() or None,
                part_number=part_number or detected_part,
                title=title,
                revision=revision,
                total_pages=document.page_count,
            )
            chunks = self.chunker.chunk(metadata, pages)
            return DocumentRecord(
                metadata=metadata,
                pages=pages,
                sections=sections,
                chunks=chunks,
            )
        except (EmptyDocumentError, UnsupportedDocumentError):
            raise
        except Exception as exc:
            raise DocumentExtractionError(f"layout extraction failed for: {path}") from exc
        finally:
            document.close()  # type: ignore[no-untyped-call]

    def _extract_pages(
        self, document: pymupdf.Document, digest: str
    ) -> tuple[list[DocumentPage], list[DocumentSection]]:
        pages: list[DocumentPage] = []
        sections: list[DocumentSection] = []
        current_section: str | None = None
        for page_index in range(document.page_count):
            page = document.load_page(page_index)  # type: ignore[no-untyped-call]
            page_number = page_index + 1
            inherited_section = current_section
            page_dict: dict[str, Any] = page.get_text("dict", sort=True)
            raw_blocks: list[dict[str, Any]] = page_dict.get("blocks", [])
            font_sizes = [
                float(span.get("size", 0.0))
                for block in raw_blocks
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text", "")).strip()
            ]
            median_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 0.0
            blocks: list[DocumentBlock] = []
            for raw_index, raw_block in enumerate(raw_blocks):
                if raw_block.get("type") != 0:
                    continue
                lines = raw_block.get("lines", [])
                text = "\n".join(
                    "".join(str(span.get("text", "")) for span in line.get("spans", []))
                    for line in lines
                ).strip()
                if not text:
                    continue
                maximum_size = max(
                    (
                        float(span.get("size", 0.0))
                        for line in lines
                        for span in line.get("spans", [])
                    ),
                    default=0.0,
                )
                kind = self._block_kind(text, maximum_size, median_size)
                block_id = _stable_id("block", f"{digest}|{page_number}|{raw_index}|{text}")
                if kind is BlockKind.HEADING:
                    current_section = text.replace("\n", " ")
                    section_id = _stable_id(
                        "section", f"{digest}|{page_number}|{block_id}|{current_section}"
                    )
                    sections.append(
                        DocumentSection(
                            section_id=section_id,
                            title=current_section,
                            page=page_number,
                            heading_block_id=block_id,
                        )
                    )
                blocks.append(
                    DocumentBlock(
                        block_id=block_id,
                        page=page_number,
                        reading_order=raw_index * 2,
                        kind=kind,
                        text=text,
                        section=current_section,
                        bbox=_bbox(raw_block.get("bbox")),
                    )
                )
            tables = self._extract_tables(
                page,
                digest,
                page_number,
                inherited_section,
                blocks,
            )
            blocks = [
                block
                for block in blocks
                if not any(self._contained_by(block.bbox, table.bbox) for table in tables)
            ]
            machine_characters = sum(len(block.text.strip()) for block in blocks)
            status = (
                ExtractionStatus.REQUIRES_OCR
                if machine_characters < self.ocr_minimum_characters and not tables
                else ExtractionStatus.COMPLETE
            )
            warnings = (
                ["insufficient machine-readable text; OCR or manual processing required"]
                if status is ExtractionStatus.REQUIRES_OCR
                else []
            )
            pages.append(
                DocumentPage(
                    page_number=page_number,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    extraction_status=status,
                    machine_readable_characters=machine_characters,
                    image_count=len(page.get_images(full=True)),
                    blocks=blocks,
                    tables=tables,
                    section_ids=[
                        section.section_id
                        for section in sections
                        if section.page == page_number
                    ],
                    warnings=warnings,
                )
            )
        return pages, sections

    def _extract_tables(
        self,
        page: pymupdf.Page,
        digest: str,
        page_number: int,
        inherited_section: str | None,
        blocks: list[DocumentBlock],
    ) -> list[DocumentTable]:
        output: list[DocumentTable] = []
        finder = page.find_tables()  # type: ignore[no-untyped-call]
        for table_index, table in enumerate(finder.tables):
            extracted = table.extract()
            clean = [
                [str(cell or "").replace("\n", " ").strip() for cell in row]
                for row in extracted
                if row
            ]
            if not clean or not clean[0]:
                continue
            width = max(len(row) for row in clean)
            normalized = [row + [""] * (width - len(row)) for row in clean]
            headers = normalized[0]
            if not any(headers):
                headers = [f"column_{index + 1}" for index in range(width)]
            table_id = _stable_id(
                "table", f"{digest}|{page_number}|{table_index}|{normalized}"
            )
            table_box = _bbox(table.bbox)
            preceding_headings = [
                block
                for block in blocks
                if block.kind is BlockKind.HEADING
                and block.bbox is not None
                and table_box is not None
                and block.bbox.y0 <= table_box.y0
            ]
            section = (
                max(
                    preceding_headings,
                    key=lambda block: block.bbox.y0 if block.bbox is not None else -1.0,
                ).text
                if preceding_headings
                else inherited_section
            )
            output.append(
                DocumentTable(
                    table_id=table_id,
                    page=page_number,
                    reading_order=table_index * 2 + 1,
                    headers=headers,
                    rows=normalized[1:],
                    section=section,
                    bbox=table_box,
                )
            )
        return output

    @staticmethod
    def _block_kind(text: str, maximum_size: float, median_size: float) -> BlockKind:
        compact = text.replace("\n", " ").strip()
        if len(compact) <= 120 and (
            (median_size > 0 and maximum_size >= median_size * 1.18)
            or (compact.isupper() and any(character.isalpha() for character in compact))
        ):
            return BlockKind.HEADING
        if compact.startswith(("•", "- ", "* ")):
            return BlockKind.LIST
        return BlockKind.PARAGRAPH

    @staticmethod
    def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return match.group(1) if match else None

    @staticmethod
    def _detect_part_number(filename: str, text: str) -> str | None:
        matches = _PART_NUMBER.findall(f"{filename} {text[:2000]}")
        return matches[0] if matches else None

    @staticmethod
    def _contained_by(inner: BoundingBox | None, outer: BoundingBox | None) -> bool:
        if inner is None or outer is None:
            return False
        return (
            inner.x0 >= outer.x0 - 1
            and inner.y0 >= outer.y0 - 1
            and inner.x1 <= outer.x1 + 1
            and inner.y1 <= outer.y1 + 1
        )
