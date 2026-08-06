"""The interface every translation backend implements.

Why a Protocol with a context object, not just `translate(text) -> str`
--------------------------------------------------------------------------
Google Translate (via `deep_translator`) is a bare phrase-level API: it
takes a string, returns a string, and knows nothing about glossaries or
protected entities -- those are applied entirely at the caller level via
placeholder substitution (see `text.protect`). An LLM backend is
different in kind, not just in quality: it can be handed the entity list
and glossary directly in a prompt and asked to honor them, and it can use
surrounding page context that a phrase-level API has no way to accept.
`TranslationContext` carries that richer information uniformly to every
backend; a backend that has no use for a field (Google ignores
`entities`, `glossary`, and `page_context` entirely) simply doesn't read
it.

`uses_placeholder_protection` is the one backend-specific switch
`Translator` consults. For a phrase-level backend, replacing entities and
numbers with `[[N]]` placeholders before translation is the ONLY way to
guarantee they survive verbatim. For an LLM backend, doing the same thing
is actively counterproductive -- placeholdering every number in a
financial-statement sentence can leave `[[0]] [[1]] [[2]] [[3]]`, which
destroys exactly the sentence-level context an LLM would otherwise use to
translate well. Backends that want the entity/number list preserved via
prompt instructions instead (verified after the fact, not enforced by
placeholder substitution) set this to False.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Status = Literal["ok", "failed", "identical", "refused"]


@dataclass(frozen=True)
class TranslationContext:
    source_lang: str
    target_lang: str
    entities: tuple[str, ...] = ()
    glossary: Mapping[str, str] = field(default_factory=dict)
    page_context: str | None = None
    """Surrounding page text, for backends that can use it. None for
    backends (or call sites) that don't have or want it."""


@dataclass(frozen=True)
class TranslationResult:
    text: str | None
    status: Status
    detail: str | None = None
    """Human-readable detail for a non-"ok" status -- an error message,
    or why a refusal happened. Never used for control flow, only for
    logging/debugging."""


@dataclass(frozen=True)
class Cost:
    input_tokens: int
    output_tokens: int
    usd: float | None = None


class Backend(Protocol):
    name: str
    prefers_batch: bool
    """Whether translate_batch is meaningfully more efficient than N
    calls to translate() for this backend -- true for an LLM backend
    that benefits from batching+prompt caching, false for Google's
    per-string endpoint."""
    max_batch: int
    uses_placeholder_protection: bool

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult: ...

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]: ...

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        """Projected cost for translating `texts`, or None if the backend
        is free (e.g. Google) or estimation isn't supported."""
        ...
