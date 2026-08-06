"""Google Translate backend, via `deep_translator`'s scrape of the free
web endpoint.

No authentication, no API key, no cost -- and no SLA. This is the
zero-setup default and the recommended fallback behind a paid backend,
not a backend to depend on for a production corpus run on its own: it is
an undocumented endpoint that can change or rate-limit without notice.

Ignores `TranslationContext.entities`, `.glossary`, and `.page_context`
entirely -- it is a bare phrase-level API with no concept of any of
them. `Translator` compensates by placeholdering entities and numbers
before the call (`uses_placeholder_protection = True`) and restoring them
afterward.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from deep_translator import GoogleTranslator

from palimpsest.translate.backend import Cost, TranslationContext, TranslationResult


class GoogleBackend:
    name = "google"
    prefers_batch = False
    uses_placeholder_protection = True

    def __init__(self, attempts: int = 3, retry_pause: float = 0.6, max_batch: int = 20):
        self.attempts = attempts
        self.retry_pause = retry_pause
        self.max_batch = max_batch
        self._translators: dict[tuple[str, str], GoogleTranslator] = {}

    def _translator_for(self, ctx: TranslationContext) -> GoogleTranslator:
        key = (ctx.source_lang, ctx.target_lang)
        if key not in self._translators:
            self._translators[key] = GoogleTranslator(
                source=ctx.source_lang, target=ctx.target_lang
            )
        return self._translators[key]

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        mt = self._translator_for(ctx)
        last: str | None = None
        for attempt in range(self.attempts):
            try:
                result = mt.translate(text)
                if result:
                    return TranslationResult(text=result, status="ok")
                last = "empty response"
            except Exception as e:
                last = str(e)
            time.sleep(self.retry_pause * (attempt + 1))
        return TranslationResult(text=None, status="failed", detail=last)

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        mt = self._translator_for(ctx)
        try:
            raw = mt.translate_batch(list(texts))
        except Exception as e:
            return [TranslationResult(text=None, status="failed", detail=str(e)) for _ in texts]
        results = []
        for r in raw:
            if r:
                results.append(TranslationResult(text=r, status="ok"))
            else:
                results.append(
                    TranslationResult(text=None, status="failed", detail="empty response")
                )
        return results

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        return None  # free
