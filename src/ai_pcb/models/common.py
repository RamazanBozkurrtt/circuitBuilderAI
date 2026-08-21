from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base model that rejects accidental fields and mutation-time invalidity."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class TimestampedModel(StrictModel):
    created_at: datetime = Field(default_factory=utc_now)
