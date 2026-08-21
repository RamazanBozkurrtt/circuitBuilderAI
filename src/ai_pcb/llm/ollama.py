from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from ai_pcb.llm.base import ResponseT, StructuredLLMError


class OllamaStructuredLLM:
    """Ollama transport adapter; domain code depends only on StructuredLLM."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("an Ollama model must be configured")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.client_factory = client_factory or (
            lambda: httpx.Client(timeout=self.timeout_seconds)
        )

    def complete(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        system_prompt: str | None = None,
    ) -> ResponseT:
        messages: list[dict[str, str]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        request = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "format": response_model.model_json_schema(),
            "options": {"temperature": 0, "seed": 0},
        }
        response = self._post_with_retry(request)
        try:
            envelope: dict[str, Any] = response.json()
            content = envelope["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            parsed = json.loads(content)
            return response_model.model_validate(parsed, strict=True)
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise StructuredLLMError("Ollama returned invalid structured output") from exc

    def _post_with_retry(self, request: dict[str, object]) -> httpx.Response:
        last_error: Exception | None = None
        with self.client_factory() as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(f"{self.base_url}/api/chat", json=request)
                    response.raise_for_status()
                    return response
                except (httpx.TransportError, httpx.TimeoutException) as exc:
                    last_error = exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        raise StructuredLLMError(
                            f"Ollama rejected the request with HTTP {exc.response.status_code}"
                        ) from exc
                    last_error = exc
                if attempt == self.max_retries:
                    break
        raise StructuredLLMError("Ollama transport failed after bounded retries") from last_error
