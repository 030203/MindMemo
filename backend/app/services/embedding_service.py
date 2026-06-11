from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request

from app.core.config import settings

ALNUM_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
CHINESE_SEQ_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        return vector
    return [value / norm for value in vector]


def _resize(vector: list[float], *, size: int) -> list[float]:
    if len(vector) == size:
        return vector
    if len(vector) > size:
        return vector[:size]
    return vector + [0.0] * (size - len(vector))


class EmbeddingService:
    def signature(self) -> str:
        return settings.embedding_signature

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        if settings.embedding_provider == "openai_compatible":
            try:
                return self._embed_with_openai_compatible(texts)
            except Exception:
                return [self._embed_with_local_hash(text) for text in texts]

        return [self._embed_with_local_hash(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _embed_with_local_hash(self, text: str) -> list[float]:
        dimension = settings.embedding_dimension
        vector = [0.0] * dimension
        compact = " ".join(text.split()).strip().lower()
        if not compact:
            return vector

        terms = self._extract_terms(compact)
        if not terms:
            terms = compact.split()

        for term in terms:
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            primary_index = int.from_bytes(digest[:4], "big") % dimension
            secondary_index = int.from_bytes(digest[4:8], "big") % dimension
            weight = 1.0 + (digest[8] / 255.0)
            vector[primary_index] += weight
            vector[secondary_index] += weight * 0.5

        return _normalize(vector)

    def _extract_terms(self, text: str) -> list[str]:
        normalized: list[str] = []

        for token in ALNUM_TOKEN_RE.findall(text):
            if token:
                normalized.append(token)

        for sequence in CHINESE_SEQ_RE.findall(text):
            if len(sequence) <= 4:
                normalized.append(sequence)
                continue

            normalized.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))

        return list(dict.fromkeys(token for token in normalized if token.strip()))

    def _embed_with_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        if not settings.openai_base_url or not settings.openai_api_key:
            raise ValueError("OPENAI_BASE_URL and OPENAI_API_KEY are required for openai_compatible embeddings")

        base_url = settings.openai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        body = json.dumps(
            {
                "model": settings.embedding_model,
                "input": texts,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url=f"{base_url}/embeddings",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.openai_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.embedding_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Embedding request failed: {exc.code} {detail}") from exc

        items = payload.get("data") or []
        if len(items) != len(texts):
            raise RuntimeError("Embedding response count does not match request count")

        vectors: list[list[float]] = []
        for item in items:
            raw = item.get("embedding")
            if not isinstance(raw, list):
                raise RuntimeError("Embedding response payload is missing vector data")
            vector = [float(value) for value in raw]
            vectors.append(_normalize(_resize(vector, size=settings.embedding_dimension)))

        return vectors


embedding_service = EmbeddingService()
