from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from ai_pcb.models.common import Identifier
from ai_pcb.models.evidence import Evidence


class EvidenceStoreError(RuntimeError):
    pass


class EvidenceNotFoundError(EvidenceStoreError):
    pass


class DuplicateEvidenceError(EvidenceStoreError):
    pass


class EvidenceStore:
    """One validated JSON document per evidence item; parsing comes in a later phase."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, evidence_id: str) -> Path:
        # Re-validate identifiers before they participate in paths.
        from pydantic import TypeAdapter

        safe_id = TypeAdapter(Identifier).validate_python(evidence_id)
        return self.root / f"{safe_id}.json"

    def add(self, evidence: Evidence) -> Path:
        destination = self._path(evidence.evidence_id)
        if destination.exists():
            raise DuplicateEvidenceError(f"evidence already exists: {evidence.evidence_id}")
        payload = evidence.model_dump_json(indent=2)
        fd, temporary_name = tempfile.mkstemp(prefix=".evidence-", dir=self.root, text=True)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.rename(destination)
            except FileExistsError as exc:
                raise DuplicateEvidenceError(
                    f"evidence already exists: {evidence.evidence_id}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def get(self, evidence_id: str) -> Evidence:
        path = self._path(evidence_id)
        if not path.is_file():
            raise EvidenceNotFoundError(f"unknown evidence reference: {evidence_id}")
        return Evidence.model_validate_json(path.read_text(encoding="utf-8"))

    def contains(self, evidence_id: str) -> bool:
        return self._path(evidence_id).is_file()

    def require_all(self, evidence_ids: Iterable[str]) -> None:
        missing = sorted({item for item in evidence_ids if not self.contains(item)})
        if missing:
            raise EvidenceNotFoundError(f"unknown evidence references: {', '.join(missing)}")

    def list(self) -> list[Evidence]:
        return [
            Evidence.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("*.json"))
        ]
