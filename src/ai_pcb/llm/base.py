from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class StructuredLLMError(RuntimeError):
    """The provider did not return locally validated structured output."""


class StructuredLLM(Protocol):
    def complete(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        system_prompt: str | None = None,
    ) -> ResponseT: ...

