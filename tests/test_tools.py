from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from ai_pcb.tools.registry import (
    ToolDefinition,
    ToolExecutionError,
    ToolRegistry,
    UnknownToolError,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


def test_registered_typed_tool_executes() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=lambda value: EchoOutput(message=value.message),
        )
    )
    assert registry.execute("echo", {"message": "safe"}) == EchoOutput(message="safe")


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(UnknownToolError, match="not allowlisted"):
        ToolRegistry().execute("unknown", {})


def test_tool_arguments_do_not_silently_coerce() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=lambda value: EchoOutput(message=value.message),
        )
    )
    with pytest.raises(ToolExecutionError):
        registry.execute("echo", {"message": 7})


def test_model_output_cannot_trigger_arbitrary_shell_execution() -> None:
    malicious_model_output = {
        "tool": "shell",
        "arguments": {"command": "python -c \"raise SystemExit('must never run')\""},
    }
    registry = ToolRegistry()
    with pytest.raises(UnknownToolError, match="shell"):
        registry.execute(
            str(malicious_model_output["tool"]), malicious_model_output["arguments"]
        )
