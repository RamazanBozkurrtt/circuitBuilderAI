from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import Field

from ai_pcb.models.common import Identifier, NonEmptyString, StrictModel

_PIN_ENTRY = re.compile(r'"\s*([A-Za-z0-9_]+)\s*:\s*([A-Z][0-9]{2})\s*(?:,)?\s*"')


class BoundaryScanPinMap(StrictModel):
    part_number: NonEmptyString
    acquisition_id: Identifier
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pins: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)


def parse_boundary_scan_pin_map(
    path: Path,
    *,
    part_number: str,
    acquisition_id: str,
    expected_sha256: str,
) -> BoundaryScanPinMap:
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("BSDL hash does not match trusted acquisition provenance")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("BSDL is not UTF-8 text") from exc
    normalized_part = re.sub(r"[^a-z0-9]", "", part_number.casefold())
    if normalized_part not in re.sub(r"[^a-z0-9]", "", text.casefold()):
        raise ValueError("BSDL does not identify the requested part")
    entries = _PIN_ENTRY.findall(text)
    pins = dict(entries)
    if not pins or len(pins) != len(entries):
        raise ValueError("BSDL pin map is absent or contains duplicate signal names")
    numbers = list(pins.values())
    if len(numbers) != len(set(numbers)):
        raise ValueError("BSDL pin map contains duplicate physical pin numbers")
    return BoundaryScanPinMap(
        part_number=part_number,
        acquisition_id=acquisition_id,
        sha256=actual_sha256,
        pins=pins,
    )
