"""A stand-in for `google.genai.Client`, injected via
`GeminiBackend(client=...)`.

No test may make a real network call or need a real API key -- this
reproduces just enough of the SDK's response shape (`.text`, `.candidates`,
`.prompt_feedback.block_reason`, `.models.count_tokens(...).total_tokens`)
for `translate.gemini` to be exercised end to end, including its
structured output parsing and safety-block handling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class FakeFeedback:
    block_reason: str | None = None


@dataclass
class FakeResponse:
    text: str | None
    candidates: list = field(default_factory=lambda: [object()])
    prompt_feedback: FakeFeedback | None = None


@dataclass
class FakeTokenCount:
    total_tokens: int


def ok_response(en: str) -> FakeResponse:
    return FakeResponse(text=json.dumps({"en": en}))


def batch_ok_response(pairs: dict[int, str]) -> FakeResponse:
    payload = {"translations": [{"id": i, "en": en} for i, en in pairs.items()]}
    return FakeResponse(text=json.dumps(payload))


def blocked_response(reason: str = "SAFETY") -> FakeResponse:
    return FakeResponse(text=None, candidates=[], prompt_feedback=FakeFeedback(block_reason=reason))


def malformed_response(raw_text: str) -> FakeResponse:
    return FakeResponse(text=raw_text)


class _Models:
    def __init__(self, client: FakeGeminiClient):
        self._client = client

    def generate_content(self, **kwargs):
        self._client.generate_calls.append(kwargs)
        if self._client.raise_on_generate is not None:
            raise self._client.raise_on_generate
        return self._client.responses.pop(0)

    def count_tokens(self, **kwargs):
        self._client.count_calls.append(kwargs)
        return FakeTokenCount(total_tokens=self._client.tokens_per_call)


@dataclass
class FakeGeminiClient:
    """`responses` is consumed in order by successive `generate_content()`
    calls. `raise_on_generate`, if set, is raised on every call instead
    (for exercising the transport-failure path) -- must be a real
    `google.genai.errors.APIError` instance so `translate.gemini`'s
    `except genai_errors.APIError` actually catches it."""

    responses: list[FakeResponse] = field(default_factory=list)
    raise_on_generate: Exception | None = None
    tokens_per_call: int = 10

    def __post_init__(self):
        self.generate_calls: list[dict] = []
        self.count_calls: list[dict] = []
        self.models = _Models(self)
