from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError


class UnknownToolError(LookupError):
    pass


class DuplicateToolError(ValueError):
    pass


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolDefinition[InputT: BaseModel, OutputT: BaseModel]:
    name: str
    input_model: type[InputT]
    output_model: type[OutputT]
    handler: Callable[[InputT], OutputT]


class ToolRegistry:
    """Explicit typed allowlist. No shell or code execution tool is registered."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register(self, definition: ToolDefinition[Any, Any]) -> None:
        if definition.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def execute(self, name: str, arguments: object) -> BaseModel:
        try:
            definition = self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"tool is not allowlisted: {name}") from exc
        try:
            typed_input = definition.input_model.model_validate(arguments, strict=True)
            raw_output = definition.handler(typed_input)
            return cast(
                BaseModel, definition.output_model.model_validate(raw_output, strict=True)
            )
        except ValidationError as exc:
            raise ToolExecutionError(f"tool validation failed: {name}") from exc

    def schemas(self) -> dict[str, dict[str, object]]:
        return {
            name: definition.input_model.model_json_schema()
            for name, definition in self._tools.items()
        }
