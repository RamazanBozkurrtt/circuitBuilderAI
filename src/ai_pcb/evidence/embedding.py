from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding

from ai_pcb.evidence.errors import EmbeddingError


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingCache:
    """Content-addressed JSON cache; entries are isolated by model identity."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, model_name: str, text: str) -> Path:
        key = hashlib.sha256(f"{model_name}\0{text}".encode()).hexdigest()
        return self.root / f"{key}.json"

    def get(self, model_name: str, text: str) -> list[float] | None:
        path = self._path(model_name, text)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or not all(
                isinstance(item, int | float) for item in value
            ):
                raise ValueError("cached embedding is invalid")
            return [float(item) for item in value]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"invalid embedding cache entry: {path}") from exc

    def put(self, model_name: str, text: str, vector: list[float]) -> None:
        path = self._path(model_name, text)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(vector, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)


class FastEmbedProvider:
    """Lazy local ONNX embedder, independent of Ollama and safe for CPU operation."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-small-en-v1.5",
        device: str = "cpu",
        cache_dir: Path | None = None,
        batch_size: int = 16,
    ) -> None:
        if not model_name.strip():
            raise ValueError("embedding model must be configured")
        if device not in {"cpu", "cuda"}:
            raise ValueError("embedding device must be 'cpu' or 'cuda'")
        if batch_size < 1:
            raise ValueError("embedding batch size must be positive")
        self._model_name = model_name
        self.device = device
        self.cache = EmbeddingCache(cache_dir) if cache_dir is not None else None
        self.batch_size = batch_size
        self._model: TextEmbedding | None = None
        self._dimension: int | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            vector = self.embed_query("embedding dimension probe")
            self._dimension = len(vector)
        return self._dimension

    def _load(self) -> TextEmbedding:
        if self._model is None:
            try:
                providers = (
                    ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    if self.device == "cuda"
                    else ["CPUExecutionProvider"]
                )
                model_cache = str(self.cache.root / "models") if self.cache else None
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=model_cache,
                    providers=providers,
                )
            except Exception as exc:
                raise EmbeddingError(
                    f"failed to load local embedding model {self.model_name!r} on {self.device}"
                ) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float] | None] = [None] * len(texts)
        missing_positions: list[int] = []
        missing_texts: list[str] = []
        for index, text in enumerate(texts):
            cached = self.cache.get(self.model_name, text) if self.cache else None
            if cached is None:
                missing_positions.append(index)
                missing_texts.append(text)
            else:
                results[index] = cached
        if missing_texts:
            model = self._load()
            for start in range(0, len(missing_texts), self.batch_size):
                batch_texts = missing_texts[start : start + self.batch_size]
                batch_positions = missing_positions[start : start + self.batch_size]
                try:
                    vectors = [
                        [float(value) for value in vector]
                        for vector in model.embed(batch_texts)
                    ]
                except Exception as exc:
                    raise EmbeddingError("local embedding generation failed") from exc
                if len(vectors) != len(batch_texts):
                    raise EmbeddingError("embedding provider returned the wrong vector count")
                for position, text, vector in zip(
                    batch_positions, batch_texts, vectors, strict=True
                ):
                    if not vector:
                        raise EmbeddingError("embedding provider returned an empty vector")
                    results[position] = vector
                    if self.cache:
                        self.cache.put(self.model_name, text, vector)
        complete = [result for result in results if result is not None]
        if len(complete) != len(texts):
            raise EmbeddingError("embedding generation did not complete")
        dimensions = {len(vector) for vector in complete}
        if len(dimensions) != 1:
            raise EmbeddingError("embedding dimensions are inconsistent")
        self._dimension = dimensions.pop()
        return complete

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]
