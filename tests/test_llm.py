from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from ai_pcb.llm.base import StructuredLLMError
from ai_pcb.llm.ollama import OllamaStructuredLLM


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: str
    score: int


def adapter_for(handler: httpx.MockTransport) -> OllamaStructuredLLM:
    return OllamaStructuredLLM(
        base_url="http://ollama.test",
        model="configured-test-model",
        timeout_seconds=1,
        max_retries=1,
        client_factory=lambda: httpx.Client(transport=handler),
    )


def test_malformed_ollama_output_fails_closed() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"message": {"content": "not valid json"}}, request=request
        )
    )
    with pytest.raises(StructuredLLMError, match="invalid structured output"):
        adapter_for(transport).complete("choose", Answer)


def test_valid_mocked_structured_output_parses_and_sends_schema() -> None:
    captured: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps({"choice": "A", "score": 7})}},
            request=request,
        )

    result = adapter_for(httpx.MockTransport(respond)).complete("choose", Answer)
    assert result == Answer(choice="A", score=7)
    assert captured["format"] == Answer.model_json_schema()
    assert captured["options"] == {"temperature": 0, "seed": 0}


def test_transport_retry_is_bounded() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(StructuredLLMError, match="bounded retries"):
        adapter_for(httpx.MockTransport(respond)).complete("choose", Answer)
    assert calls == 2


def test_schema_invalid_output_fails_closed_without_coercion() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": '{"choice":"A","score":"7"}'}},
            request=request,
        )
    )
    with pytest.raises(StructuredLLMError):
        adapter_for(transport).complete("choose", Answer)
