from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from ai_pcb.llm.ollama import OllamaStructuredLLM


class LiveResponse(BaseModel):
    acknowledgement: str


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("RUN_OLLAMA_INTEGRATION"), reason="live Ollama not requested")
def test_live_ollama_structured_output() -> None:
    model = os.environ["OLLAMA_MODEL"]
    adapter = OllamaStructuredLLM(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=model,
        timeout_seconds=30,
        max_retries=1,
    )
    result = adapter.complete(
        "Return an acknowledgement containing the word ok.", LiveResponse
    )
    assert result.acknowledgement

