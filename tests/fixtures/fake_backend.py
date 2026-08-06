"""A translation backend test double implementing
`palimpsest.translate.backend.Backend`.

No test in this project may make a real network call (Google's endpoint
is an undocumented scrape with no SLA; an LLM backend costs money and
isn't deterministic). This stands in for any real backend so
Translator/Cache logic can be tested without either.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from palimpsest.translate.backend import Cost, TranslationContext, TranslationResult


class FakeBackend:
    name = "fake"
    prefers_batch = True
    max_batch = 25

    def __init__(
        self,
        translate_fn: Callable[[str], str] | None = None,
        uses_placeholder_protection: bool = True,
    ):
        self.uses_placeholder_protection = uses_placeholder_protection
        self._translate_fn = translate_fn or (lambda s: s.upper())
        self.calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        self.calls.append(text)
        return TranslationResult(text=self._translate_fn(text), status="ok")

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        self.batch_calls.append(list(texts))
        return [self.translate(t, ctx) for t in texts]

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        return None


class FailingBackend:
    """Every call fails -- for testing the honest-cache "failed" path."""

    name = "failing"
    prefers_batch = False
    max_batch = 20
    uses_placeholder_protection = True

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        return TranslationResult(text=None, status="failed", detail="simulated failure")

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        return [self.translate(t, ctx) for t in texts]

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        return None
