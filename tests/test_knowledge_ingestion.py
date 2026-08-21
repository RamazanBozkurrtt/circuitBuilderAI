from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

from ai_pcb.evidence.chunking import EngineeringChunker
from ai_pcb.evidence.errors import DocumentExtractionError, UnsupportedDocumentError
from ai_pcb.evidence.ingestion import PdfDocumentIngestor
from ai_pcb.models.evidence import EvidenceSource
from ai_pcb.models.knowledge import (
    BlockKind,
    BoundingBox,
    ChunkKind,
    DocumentBlock,
    DocumentMetadata,
    DocumentPage,
    DocumentTable,
    ExtractionStatus,
)


def write_datasheet(path: Path, *, core_voltage: str = "1.2 V") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    first = document.new_page(width=600, height=800)
    first.insert_text((50, 60), "ADAU1467 AUDIO DSP", fontsize=18)
    first.insert_text((50, 90), "Revision B", fontsize=10)
    first.insert_text((50, 130), "POWER REQUIREMENTS", fontsize=15)
    first.insert_text(
        (50, 160),
        f"The DVDD digital processing core supply requires {core_voltage} under normal operation.",
        fontsize=10,
    )
    second = document.new_page(width=600, height=800)
    second.insert_text((50, 60), "CLOCK REQUIREMENTS", fontsize=15)
    second.insert_text((50, 90), "MCLK is the master clock input. BCLK is pin 12.", fontsize=10)
    document.save(path)
    document.close()


def metadata() -> DocumentMetadata:
    digest = "a" * 64
    return DocumentMetadata(
        document_id="doc-test",
        source_file="synthetic.pdf",
        sha256=digest,
        source_type=EvidenceSource.DATASHEET,
        manufacturer="Analog Devices",
        part_number="ADAU1467",
        title="Synthetic DSP Datasheet",
        revision="B",
        total_pages=1,
    )


def test_pdf_ingestion_preserves_page_layout_and_stable_ids(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "datasheets" / "ADAU1467.pdf"
    write_datasheet(path)
    ingestor = PdfDocumentIngestor(ocr_minimum_characters=10)
    first = ingestor.ingest(path, manufacturer="Analog Devices", part_number="ADAU1467")
    second = ingestor.ingest(path, manufacturer="Analog Devices", part_number="ADAU1467")

    assert first.metadata.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert first.metadata.document_id == second.metadata.document_id
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert [page.page_number for page in first.pages] == [1, 2]
    assert all(block.bbox is not None for page in first.pages for block in page.blocks)
    clock = next(chunk for chunk in first.chunks if "MCLK" in chunk.text)
    assert clock.page == 2
    assert clock.section == "CLOCK REQUIREMENTS"
    assert "bbox(" in clock.locator


def test_changed_pdf_hash_and_document_id_are_detected(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "datasheets" / "ADAU1467.pdf"
    write_datasheet(path)
    ingestor = PdfDocumentIngestor(ocr_minimum_characters=10)
    original = ingestor.ingest(path)
    write_datasheet(path, core_voltage="1.1 V")
    changed = ingestor.ingest(path)
    assert changed.metadata.sha256 != original.metadata.sha256
    assert changed.metadata.document_id != original.metadata.document_id


def test_table_chunk_preserves_headers_rows_and_section() -> None:
    page = DocumentPage(
        page_number=1,
        width=600.0,
        height=800.0,
        extraction_status=ExtractionStatus.COMPLETE,
        machine_readable_characters=100,
        blocks=[
            DocumentBlock(
                block_id="block-heading",
                page=1,
                reading_order=0,
                kind=BlockKind.HEADING,
                text="ELECTRICAL CHARACTERISTICS",
                section="ELECTRICAL CHARACTERISTICS",
                bbox=BoundingBox(x0=10.0, y0=10.0, x1=300.0, y1=30.0),
            )
        ],
        tables=[
            DocumentTable(
                table_id="table-power",
                page=1,
                reading_order=1,
                headers=["Parameter", "Min", "Typ", "Max", "Unit"],
                rows=[["DVDD", "1.14", "1.20", "1.26", "V"]],
                section="ELECTRICAL CHARACTERISTICS",
                bbox=BoundingBox(x0=10.0, y0=40.0, x1=550.0, y1=100.0),
            )
        ],
    )
    chunks = EngineeringChunker(max_characters=500, target_characters=300).chunk(
        metadata(), [page]
    )
    table = next(chunk for chunk in chunks if chunk.kind is ChunkKind.TABLE)
    assert table.text.splitlines() == [
        "Parameter | Min | Typ | Max | Unit",
        "DVDD | 1.14 | 1.20 | 1.26 | V",
    ]
    assert table.section == "ELECTRICAL CHARACTERISTICS"
    assert table.table_ids == ["table-power"]


def test_pdf_table_ingestion_preserves_headers_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "datasheets" / "table.pdf"
    path.parent.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    x_coordinates = [50, 200, 300, 400]
    y_coordinates = [50, 80, 110]
    for x_coordinate in x_coordinates:
        page.draw_line(
            (x_coordinate, y_coordinates[0]), (x_coordinate, y_coordinates[-1])
        )
    for y_coordinate in y_coordinates:
        page.draw_line(
            (x_coordinates[0], y_coordinate), (x_coordinates[-1], y_coordinate)
        )
    for x_coordinate, text in zip(
        [60, 210, 310], ["Parameter", "Typical", "Unit"], strict=True
    ):
        page.insert_text((x_coordinate, 70), text, fontsize=9)
    for x_coordinate, text in zip([60, 210, 310], ["DVDD", "1.2", "V"], strict=True):
        page.insert_text((x_coordinate, 100), text, fontsize=9)
    document.save(path)
    document.close()

    record = PdfDocumentIngestor(ocr_minimum_characters=0).ingest(path)
    table = record.pages[0].tables[0]
    assert table.headers == ["Parameter", "Typical", "Unit"]
    assert table.rows == [["DVDD", "1.2", "V"]]
    table_chunk = next(chunk for chunk in record.chunks if chunk.kind is ChunkKind.TABLE)
    assert table_chunk.text == "Parameter | Typical | Unit\nDVDD | 1.2 | V"


def test_low_text_page_is_marked_for_ocr(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "app_notes" / "scan.pdf"
    path.parent.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 50), "scan")
    document.save(path)
    document.close()
    record = PdfDocumentIngestor(ocr_minimum_characters=40).ingest(path)
    assert record.pages[0].extraction_status is ExtractionStatus.REQUIRES_OCR
    assert record.pages[0].warnings


def test_unsupported_and_corrupt_documents_fail_explicitly(tmp_path: Path) -> None:
    text = tmp_path / "knowledge" / "datasheets" / "part.txt"
    text.parent.mkdir(parents=True)
    text.write_text("not pdf", encoding="utf-8")
    with pytest.raises(UnsupportedDocumentError):
        PdfDocumentIngestor().ingest(text)
    corrupt = text.with_suffix(".pdf")
    corrupt.write_bytes(b"not a pdf")
    with pytest.raises(DocumentExtractionError):
        PdfDocumentIngestor().ingest(corrupt)
