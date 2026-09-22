from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from cloudeo.config import Settings


class JevError(RuntimeError):
    pass


class JevClient(ABC):
    @abstractmethod
    async def decide(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OpenRouterJevClient(JevClient):
    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key:
            raise JevError("OPENROUTER_API_KEY is required when CLOUDEO_JEV_BACKEND=openrouter")
        self.url = settings.jev_url
        self.model = settings.jev_model
        self.api_key = settings.openrouter_api_key

    async def decide(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        payload = {"model": self.model, "state": state, "questions": questions}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.url, headers=headers, json=payload)
        if response.is_error:
            body = response.text[:1000]
            raise JevError(f"Jev request failed: HTTP {response.status_code}: {body}")
        data = response.json()
        if "answers" not in data:
            raise JevError(f"Unexpected Jev response: {json.dumps(data)[:1000]}")
        return data


class MockJevClient(JevClient):
    """Deterministic local stand-in so the full control loop runs without paid APIs."""

    async def decide(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        state_text = json.dumps(state, sort_keys=True, default=str).lower()
        for qid, question in questions.items():
            qtype = question["type"]
            if qtype == "noul":
                # Demo verifier: explicit mock failures produce a low score; all else passes.
                probability = 0.20 if "mock_fail" in state_text or "error" in state_text else 0.93
                answers[qid] = {"type": "noul", "noul": probability}
                continue

            if qtype == "choice":
                criteria = question.get("criteria") or {}
                labels = list(criteria)
                if not labels:
                    raise JevError(f"Mock choice question {qid!r} has no criteria")
                preferred = next((label for label in labels if label != "escalate"), labels[0])
                if len(labels) == 1:
                    probabilities = {preferred: 1.0}
                else:
                    remainder = 0.08 / (len(labels) - 1)
                    probabilities = {label: round(remainder, 6) for label in labels}
                    probabilities[preferred] = 0.92
                answers[qid] = {
                    "type": "choice",
                    "choice": preferred,
                    "probabilities": probabilities,
                    "confidence": 0.94,
                }
                continue

            if qtype == "score":
                levels = question.get("criteria") or []
                if not levels:
                    raise JevError(f"Mock score question {qid!r} has no criteria")
                index = len(levels) - 1
                probabilities = {str(i): 0.0 for i in range(len(levels))}
                probabilities[str(index)] = 1.0
                answers[qid] = {
                    "type": "score",
                    "score": float(index),
                    "probabilities": probabilities,
                    "confidence": 0.95,
                    "legend": {str(i): level for i, level in enumerate(levels)},
                }
                continue

            raise JevError(f"Unsupported question type: {qtype}")

        return {"id": "mock-decision", "model": "mock-jev", "provider": "local", "answers": answers}


def build_jev_client(settings: Settings) -> JevClient:
    backend = settings.jev_backend.lower()
    if backend == "openrouter":
        return OpenRouterJevClient(settings)
    if backend == "mock":
        return MockJevClient()
    raise JevError(f"Unsupported Jev backend: {settings.jev_backend}")
