from __future__ import annotations

import hashlib
from collections.abc import Iterable

from ai_pcb.models.knowledge import (
    BoundingBox,
    ChunkKind,
    DocumentBlock,
    DocumentChunk,
    DocumentMetadata,
    DocumentPage,
    DocumentTable,
)


def _identifier(prefix: str, material: str) -> str:
    return f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _union(boxes: Iterable[BoundingBox | None]) -> BoundingBox | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return BoundingBox(
        x0=min(box.x0 for box in present),
        y0=min(box.y0 for box in present),
        x1=max(box.x1 for box in present),
        y1=max(box.y1 for box in present),
    )


def _locator(page: int, box: BoundingBox | None, identifiers: list[str]) -> str:
    location = f"page={page}"
    if box is not None:
        location += f";{box.locator()}"
    if identifiers:
        location += f";items={','.join(identifiers)}"
    return location


class EngineeringChunker:
    """Layout-aware chunker that keeps sections and tables as semantic units."""

    def __init__(self, *, target_characters: int = 1800, max_characters: int = 3200) -> None:
        if target_characters < 1 or max_characters < target_characters:
            raise ValueError("chunk limits must be positive and max must be at least target")
        self.target_characters = target_characters
        self.max_characters = max_characters

    def chunk(self, metadata: DocumentMetadata, pages: list[DocumentPage]) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for page in pages:
            chunks.extend(self._page_chunks(metadata, page))
        return self._link(chunks)

    def _page_chunks(
        self, metadata: DocumentMetadata, page: DocumentPage
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        pending: list[DocumentBlock] = []
        pending_section: str | None = None

        def flush() -> None:
            nonlocal pending
            if pending:
                chunks.append(self._text_chunk(metadata, page.page_number, pending))
                pending = []

        items: list[tuple[float, int, DocumentBlock | DocumentTable]] = [
            (
                block.bbox.y0 if block.bbox is not None else float(block.reading_order),
                block.reading_order,
                block,
            )
            for block in page.blocks
        ]
        items.extend(
            (
                table.bbox.y0 if table.bbox is not None else float(table.reading_order),
                table.reading_order,
                table,
            )
            for table in page.tables
        )
        for _, _, item in sorted(items, key=lambda pair: (pair[0], pair[1])):
            if isinstance(item, DocumentTable):
                flush()
                chunks.extend(self._table_chunks(metadata, item))
                pending_section = item.section
                continue
            if pending and (
                item.section != pending_section
                or sum(len(block.text) for block in pending) + len(item.text)
                > self.target_characters
            ):
                flush()
            pending_section = item.section
            if len(item.text) > self.max_characters:
                flush()
                for text in self._split_long_text(item.text):
                    chunks.append(
                        self._text_chunk(
                            metadata,
                            page.page_number,
                            [item.model_copy(update={"text": text})],
                        )
                    )
            else:
                pending.append(item)
        flush()
        return chunks

    def _split_long_text(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        if len(paragraphs) == 1:
            paragraphs = [part.strip() for part in text.split(". ") if part.strip()]
            paragraphs = [part if part.endswith(".") else f"{part}." for part in paragraphs]
        output: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 1 > self.max_characters:
                output.append(current)
                current = ""
            if len(paragraph) > self.max_characters:
                if current:
                    output.append(current)
                    current = ""
                output.extend(
                    paragraph[start : start + self.max_characters]
                    for start in range(0, len(paragraph), self.max_characters)
                )
            else:
                current = f"{current}\n{paragraph}".strip()
        if current:
            output.append(current)
        return output

    def _text_chunk(
        self, metadata: DocumentMetadata, page: int, blocks: list[DocumentBlock]
    ) -> DocumentChunk:
        text = "\n".join(block.text for block in blocks)
        block_ids = [block.block_id for block in blocks]
        box = _union(block.bbox for block in blocks)
        section = blocks[0].section
        material = f"{metadata.sha256}|{page}|TEXT|{'|'.join(block_ids)}|{text}"
        return DocumentChunk(
            chunk_id=_identifier("chunk", material),
            document_id=metadata.document_id,
            source_file=metadata.source_file,
            document_hash=metadata.sha256,
            source_type=metadata.source_type,
            manufacturer=metadata.manufacturer,
            part_number=metadata.part_number,
            document_title=metadata.title,
            document_revision=metadata.revision,
            page=page,
            section=section,
            kind=ChunkKind.TEXT,
            text=text,
            block_ids=block_ids,
            bbox=box,
            locator=_locator(page, box, block_ids),
        )

    def _table_chunks(
        self, metadata: DocumentMetadata, table: DocumentTable
    ) -> list[DocumentChunk]:
        # Rows may be batched only when necessary; every batch repeats the full header.
        row_groups: list[list[list[str]]] = []
        current: list[list[str]] = []
        header_size = len(" | ".join(table.headers))
        current_size = header_size
        for row in table.rows:
            row_size = len(" | ".join(row)) + 1
            if current and current_size + row_size > self.max_characters:
                row_groups.append(current)
                current = []
                current_size = header_size
            current.append(row)
            current_size += row_size
        row_groups.append(current)
        chunks: list[DocumentChunk] = []
        for group_index, rows in enumerate(row_groups):
            text = "\n".join(
                [" | ".join(table.headers), *(" | ".join(row) for row in rows)]
            )
            material = (
                f"{metadata.sha256}|{table.page}|TABLE|{table.table_id}|"
                f"{group_index}|{text}"
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=_identifier("chunk", material),
                    document_id=metadata.document_id,
                    source_file=metadata.source_file,
                    document_hash=metadata.sha256,
                    source_type=metadata.source_type,
                    manufacturer=metadata.manufacturer,
                    part_number=metadata.part_number,
                    document_title=metadata.title,
                    document_revision=metadata.revision,
                    page=table.page,
                    section=table.section,
                    kind=ChunkKind.TABLE,
                    text=text,
                    table_ids=[table.table_id],
                    bbox=table.bbox,
                    locator=_locator(table.page, table.bbox, [table.table_id]),
                )
            )
        return chunks

    @staticmethod
    def _link(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        output: list[DocumentChunk] = []
        for index, chunk in enumerate(chunks):
            output.append(
                chunk.model_copy(
                    update={
                        "previous_chunk_id": chunks[index - 1].chunk_id if index else None,
                        "next_chunk_id": (
                            chunks[index + 1].chunk_id if index + 1 < len(chunks) else None
                        ),
                    }
                )
            )
        return output
