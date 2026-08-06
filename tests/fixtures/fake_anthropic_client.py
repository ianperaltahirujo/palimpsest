"""A stand-in for `anthropic.Anthropic`, injected via
`AnthropicBackend(client=...)`.

No test may make a real network call or need a real API key -- this
reproduces just enough of the SDK's response shape (`.content` blocks,
`.stop_reason`/`.stop_details`, `.messages.batches.*`) for
`translate.anthropic` to be exercised end to end, including its structured
output parsing and refusal handling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Block:
    type: str
    text: str | None = None


@dataclass
class StopDetails:
    category: str | None = None


@dataclass
class FakeMessage:
    content: list[Block]
    stop_reason: str = "end_turn"
    stop_details: StopDetails | None = None


@dataclass
class TokenCount:
    input_tokens: int


def ok_message(en: str) -> FakeMessage:
    return FakeMessage(content=[Block(type="text", text=json.dumps({"en": en}))])


def batch_ok_message(pairs: dict[int, str]) -> FakeMessage:
    payload = {"translations": [{"id": i, "en": en} for i, en in pairs.items()]}
    return FakeMessage(content=[Block(type="text", text=json.dumps(payload))])


def refused_message(category: str = "cyber") -> FakeMessage:
    return FakeMessage(
        content=[], stop_reason="refusal", stop_details=StopDetails(category=category)
    )


def malformed_message(raw_text: str) -> FakeMessage:
    return FakeMessage(content=[Block(type="text", text=raw_text)])


@dataclass
class BatchHandle:
    id: str
    processing_status: str


@dataclass
class BatchResultItem:
    custom_id: str
    result: object


@dataclass
class BatchSucceeded:
    message: FakeMessage
    type: str = "succeeded"


@dataclass
class BatchErrored:
    type: str = "errored"


class _Batches:
    def __init__(self, client: FakeAnthropicClient):
        self._client = client

    def create(self, requests):
        self._client.batch_requests = list(requests)
        return BatchHandle(id="batch_test", processing_status=self._client.batch_status_sequence[0])

    def retrieve(self, batch_id):
        seq = self._client.batch_status_sequence
        status = seq[min(self._client._poll_count, len(seq) - 1)]
        self._client._poll_count += 1
        return BatchHandle(id=batch_id, processing_status=status)

    def results(self, batch_id):
        return list(self._client.batch_results)


class _Messages:
    def __init__(self, client: FakeAnthropicClient):
        self._client = client
        self.batches = _Batches(client)

    def create(self, **kwargs):
        self._client.create_calls.append(kwargs)
        if self._client.raise_on_create is not None:
            raise self._client.raise_on_create
        return self._client.responses.pop(0)

    def count_tokens(self, **kwargs):
        self._client.count_calls.append(kwargs)
        return TokenCount(input_tokens=self._client.tokens_per_call)


@dataclass
class FakeAnthropicClient:
    """`responses` is consumed in order by successive `messages.create()`
    calls. `raise_on_create`, if set, is raised on every `create()` call
    instead (for exercising the transport-failure path)."""

    responses: list[FakeMessage] = field(default_factory=list)
    raise_on_create: Exception | None = None
    tokens_per_call: int = 10
    batch_results: list[BatchResultItem] = field(default_factory=list)
    batch_status_sequence: list[str] = field(default_factory=lambda: ["ended"])

    def __post_init__(self):
        self.create_calls: list[dict] = []
        self.count_calls: list[dict] = []
        self.batch_requests: list = []
        self._poll_count = 0
        self.messages = _Messages(self)
