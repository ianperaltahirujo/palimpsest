"""Gemini translation backend, via Google's `google-genai` SDK.

Why this exists alongside Claude
----------------------------------
Both are LLM backends and share the same protection philosophy (see
`translate.anthropic`'s module docstring) -- an LLM can be handed the
entity list and glossary directly and asked to honor them, so
placeholdering every number and name before the call would destroy
exactly the sentence-level context that makes an LLM translate well in
the first place. `uses_placeholder_protection = False` here for the same
reason, and the same `_verify()` shape (entity survival + digit-sequence
multiset) gates every response, with the same tested `[[N]]`-placeholder
retry as a fallback.

Gemini is the default backend (`[backend].name = "gemini"`) because it is
the free-tier, no-billing-setup option: an API key from Google AI Studio
(`GEMINI_API_KEY` or `GOOGLE_API_KEY` in the environment -- never accepted
from `palimpsest.toml` or a CLI flag) costs nothing to obtain, unlike
Anthropic's pay-as-you-go key. It is still an LLM, not a bare
phrase-level API like the Google Translate backend (`translate.google`) --
it is a different backend from that one and the naming is a real
potential confusion: `translate.google` wraps `deep_translator`'s free
Google Translate scrape (zero setup, no key at all, phrase-level, no
entity awareness); this module wraps the Gemini *model* API (needs a free
API key, LLM-level, entity-aware). `[backend].fallback = "anthropic"` by
default -- if Gemini's free tier rate-limits or errors, or no key is
configured, Anthropic (paid, higher quality) is tried next; a user who
wants the truly zero-setup fallback instead can set `fallback = "google"`.

Structured output uses `response_mime_type: "application/json"` with a
raw JSON Schema dict via `response_json_schema` (not a Pydantic model) --
same reasoning as the Anthropic backend's raw-dict `json_schema` output
config: no extra dependency, and the schema is small enough that
hand-writing it is clearer than a model class.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from palimpsest.config.model import GeminiBackendConfig
from palimpsest.core.errors import BackendError, DependencyError
from palimpsest.text.protect import (
    all_tokens_restored,
    build_protect_re,
    protect,
    restore,
    strip_accents,
)
from palimpsest.translate.backend import Cost, TranslationContext, TranslationResult

log = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_errors = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

# Cached 2026-08-06 from Google's published Gemini API pricing -- only
# models this backend is actually configured against by default; an
# unrecognized model (including several current Flash-Lite variants whose
# per-token price wasn't independently confirmed at the time this was
# written) makes estimate() return None rather than guess a price. See
# docs/design/backends.md.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

_NUMBER_RE = re.compile(r"\b\d[\d.,]*\b")

_SYSTEM_TEMPLATE = """You are a professional legal/financial document translator, \
translating from {source} to {target}.

Translate each paragraph faithfully. Preserve the register and structure of \
legal and financial prose; do not summarize, add, or omit content.

Do not reformat numbers, dates, or currency amounts. Reproduce every digit \
sequence exactly as it appears in the source, including whatever punctuation \
separates thousands and decimals -- do not convert between number conventions.

Do not translate the following entities -- reproduce them exactly as they \
appear in the source, verbatim, in every place they occur:
{entities_block}

Glossary -- when the source uses one of these terms, use the given translation:
{glossary_block}
"""

_SINGLE_USER_TEMPLATE = "Translate this paragraph:\n\n{text}"

_SINGLE_SCHEMA = {
    "type": "object",
    "properties": {"en": {"type": "string"}},
    "required": ["en"],
}

_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "en": {"type": "string"},
                },
                "required": ["id", "en"],
            },
        }
    },
    "required": ["translations"],
}


def _system_prompt(ctx: TranslationContext) -> str:
    """Deterministic (sorted) for the same reason as the Anthropic
    backend's version -- byte-identical text for identical configuration,
    so an entity/glossary change is visible as a cache-namespace change
    (see `translate.cache.compute_namespace`) rather than silent drift."""
    entities_block = "\n".join(f"- {e}" for e in sorted(ctx.entities)) or "(none)"
    glossary_block = (
        "\n".join(f"- {k} -> {v}" for k, v in sorted(ctx.glossary.items())) or "(none)"
    )
    return _SYSTEM_TEMPLATE.format(
        source=ctx.source_lang, target=ctx.target_lang,
        entities_block=entities_block, glossary_block=glossary_block,
    )


def _entities_re(entities: Sequence[str]):
    if not entities:
        return None
    variants = set()
    for s in entities:
        variants.add(s)
        variants.add(strip_accents(s))
    parts = [re.escape(s) for s in sorted(variants, key=len, reverse=True)]
    return re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)


def _verify(source: str, english: str, entities: Sequence[str]) -> bool:
    """Identical contract to `translate.anthropic._verify` -- see that
    module's docstring. Duplicated rather than shared because each
    backend module is meant to be readable standalone."""
    entities_re = _entities_re(entities)
    if entities_re is not None:
        mentioned = {strip_accents(m.group(0)).casefold() for m in entities_re.finditer(source)}
        present = strip_accents(english).casefold()
        if any(e not in present for e in mentioned):
            return False
    return Counter(_NUMBER_RE.findall(source)) == Counter(_NUMBER_RE.findall(english))


class GeminiBackend:
    name = "gemini"
    prefers_batch = True
    uses_placeholder_protection = False

    def __init__(
        self,
        model: str = "gemini-3.5-flash-lite",
        batch_size: int = 20,
        max_output_tokens_per_unit: int = 4096,
        client: Any | None = None,
    ):
        """`client`, if given, is used as-is instead of constructing a real
        `genai.Client()` -- the only way tests exercise this class without
        either the real package or a network call (see
        `tests/fixtures/fake_gemini_client.py`)."""
        if client is None and genai is None:
            raise DependencyError(
                "the 'google-genai' package is required for the Gemini backend -- "
                "install with `pip install palimpsest-translate[gemini]`"
            )
        self.model = model
        self.max_batch = batch_size
        self.max_output_tokens_per_unit = max_output_tokens_per_unit
        # genai.Client() resolves GEMINI_API_KEY (or GOOGLE_API_KEY) from
        # the environment on its own -- never accept a key from config or
        # argv here, so it can never end up in a committed TOML file or a
        # shell history. Unlike anthropic.Anthropic() (lenient until the
        # first real call), genai.Client() raises ValueError immediately
        # if neither variable is set -- caught here and re-raised as a
        # DependencyError so it surfaces as the same clean, actionable CLI
        # message as a missing package, not a raw SDK traceback. This is
        # the default backend, so a brand-new user with no key configured
        # yet is the expected first encounter with this path, not an edge
        # case.
        if client is not None:
            self._client: Any = client
        else:
            try:
                self._client = genai.Client()
            except ValueError as e:
                raise DependencyError(
                    "no Gemini API key found -- set $GEMINI_API_KEY (or $GOOGLE_API_KEY) in "
                    "your environment. Get a free key at https://aistudio.google.com/apikey, "
                    "or use --backend google for a no-key fallback in the meantime. "
                    f"(underlying error: {e})"
                ) from e

    @classmethod
    def from_config(cls, cfg: GeminiBackendConfig) -> GeminiBackend:
        return cls(
            model=cfg.model,
            batch_size=cfg.batch_size,
            max_output_tokens_per_unit=cfg.max_output_tokens_per_unit,
        )

    # -- single unit ------------------------------------------------------

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        outcome = self._request_one(text, ctx)
        if outcome.status != "ok":
            return outcome
        if _verify(text, outcome.text or "", ctx.entities):
            return outcome

        protect_re = build_protect_re(ctx.entities)
        protected_text, tokens = protect(text, protect_re)
        retry = self._request_one(protected_text, ctx)
        if retry.status != "ok":
            return TranslationResult(
                text=None, status="failed",
                detail="entity/number assertion failed and placeholder retry did not succeed",
            )
        restored = restore(retry.text, tokens)
        if restored is None or not all_tokens_restored(restored):
            return TranslationResult(
                text=None, status="failed",
                detail="entity/number assertion failed and the placeholder retry left an "
                "unresolved [[N]] token",
            )
        if not _verify(text, restored, ctx.entities):
            return TranslationResult(
                text=None, status="failed",
                detail="entity/number assertion failed again after the placeholder retry",
            )
        return TranslationResult(text=restored, status="ok")

    def _generate(self, prompt: str, ctx: TranslationContext, schema: dict) -> Any:
        return self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=_system_prompt(ctx),
                response_mime_type="application/json",
                response_json_schema=schema,
                max_output_tokens=self.max_output_tokens_per_unit,
                temperature=0.0,
            ),
        )

    def _request_one(self, text: str, ctx: TranslationContext) -> TranslationResult:
        try:
            response = self._generate(
                _SINGLE_USER_TEMPLATE.format(text=text), ctx, _SINGLE_SCHEMA
            )
        except genai_errors.APIError as e:
            return TranslationResult(text=None, status="failed", detail=str(e))

        blocked = _block_reason(response)
        if blocked is not None:
            return TranslationResult(text=None, status="refused", detail=blocked)

        raw = getattr(response, "text", None)
        if raw is None:
            return TranslationResult(text=None, status="failed", detail="no text in response")
        try:
            english = json.loads(raw)["en"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return TranslationResult(
                text=None, status="failed", detail=f"malformed structured output: {e}"
            )
        return TranslationResult(text=english, status="ok")

    # -- batch --------------------------------------------------------------

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        if not texts:
            return []
        units = "\n\n".join(f"[{i}]\n{t}" for i, t in enumerate(texts))
        user = (
            "Translate each of the following paragraphs. Respond with one entry per "
            "paragraph, using the same id.\n\n" + units
        )
        try:
            response = self._generate(user, ctx, _BATCH_SCHEMA)
        except genai_errors.APIError as e:
            return [TranslationResult(text=None, status="failed", detail=str(e)) for _ in texts]

        blocked = _block_reason(response)
        if blocked is not None:
            return [TranslationResult(text=None, status="refused", detail=blocked) for _ in texts]

        raw = getattr(response, "text", None)
        by_id: dict[int, str] = {}
        if raw is not None:
            try:
                for entry in json.loads(raw)["translations"]:
                    by_id[entry["id"]] = entry["en"]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                log.warning("malformed batch structured output: %s", e)

        results = []
        for i, src in enumerate(texts):
            english = by_id.get(i)
            if english is None:
                results.append(
                    TranslationResult(
                        text=None, status="failed", detail=f"missing id {i} in batch response"
                    )
                )
            elif _verify(src, english, ctx.entities):
                results.append(TranslationResult(text=english, status="ok"))
            else:
                results.append(
                    TranslationResult(
                        text=None, status="failed", detail="entity/number assertion failed"
                    )
                )
        return results

    # -- cost ---------------------------------------------------------------

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        pricing = PRICING_USD_PER_MTOK.get(self.model)
        system = _system_prompt(ctx)
        total_input = 0
        try:
            for t in texts:
                counted = self._client.models.count_tokens(
                    model=self.model,
                    contents=_SINGLE_USER_TEMPLATE.format(text=t),
                    config=genai_types.GenerateContentConfig(system_instruction=system),
                )
                total_input += counted.total_tokens
        except genai_errors.APIError as e:
            raise BackendError(f"could not estimate cost: {e}") from e
        # Output tokens are unknown until translation happens; translated
        # prose is close in length to source, so input count is used as
        # the output estimate too, same as the Anthropic backend.
        estimated_output = total_input
        usd = None
        if pricing is not None:
            in_rate, out_rate = pricing
            usd = (total_input / 1_000_000) * in_rate + (estimated_output / 1_000_000) * out_rate
        return Cost(input_tokens=total_input, output_tokens=estimated_output, usd=usd)


def _block_reason(response: Any) -> str | None:
    """None if the response is usable; a human-readable reason if the
    prompt or the response was blocked by Gemini's safety filtering.
    Deliberately does NOT read `candidate.finish_reason` -- a known SDK
    issue hangs on certain safety-related finish_reason values
    (googleapis/python-genai#2024). `prompt_feedback.block_reason` and an
    empty/missing `candidates` list are enough to detect a block without
    touching that attribute."""
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason:
        return str(block_reason)
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return "no candidates in response (likely blocked)"
    return None
