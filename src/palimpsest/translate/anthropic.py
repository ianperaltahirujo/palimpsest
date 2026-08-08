"""Claude (Anthropic) translation backend.

Why placeholder protection is OFF for this backend
----------------------------------------------------
`uses_placeholder_protection = False`. Google is a phrase-level API with no
concept of "this word is a company name" -- placeholdering entities and
numbers before the call is the only way to guarantee they survive. An LLM
is different in kind: it can be handed the entity list and glossary
directly and asked to honor them, and it reads the whole sentence, so
placeholdering every number in a financial-statement line (`[[0]] [[1]]
[[2]] [[3]]`) would destroy exactly the context that makes it translate
well in the first place (see `translate.backend`'s module docstring).

So here, protection is an assertion, not a transformation: entities and
glossary go in a cached system prompt; after each response, `_verify()`
checks mechanically that (a) every entity the source actually mentions is
still present, case/accent-insensitively, in the output, and (b) the
source and output contain the exact same multiset of digit-sequence
tokens (`\\d[\\d.,]*`) -- which is why the system prompt also instructs
Claude not to reformat numbers (Spanish `1.234,56` must stay `1.234,56`,
not become `1,234.56`): the check is only meaningful if Claude isn't
*supposed* to change the punctuation. On a verification failure, the unit
is retried exactly once with the existing tested `[[N]]` placeholder
scheme (same mechanism the Google backend always uses) rather than
shipped with a silently dropped entity or number.

Refusals (`stop_reason == "refusal"`) map to the cache's `"refused"`
status -- distinct from `"failed"`: not a transient error, and a
placeholder retry will not fix a policy decline, so it is not attempted.

Batching: `translate_batch()` sends one structured-output request per
chunk (or, with `use_batches_api=True`, submits the chunk to the async
Batches API at 50% cost and polls). Results are matched strictly by an
`id` field the model echoes back, never by list position.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Sequence
from typing import Any

from palimpsest.config.model import AnthropicBackendConfig
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
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]

# Cached 2026-06-24 -- see docs/design/backends.md for the full table and
# sourcing note. Only the models this backend is actually configured
# against by default; an unrecognized model makes estimate() return None
# rather than guess a price.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
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
    "additionalProperties": False,
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
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def _system_prompt(ctx: TranslationContext) -> str:
    """Deterministic (sorted) so repeated calls share a byte-identical
    prefix -- required for prompt caching to ever hit, and for entity/
    glossary changes to be visible as a namespace change (see
    `translate.cache.compute_namespace`) rather than silent drift."""
    entities_block = "\n".join(f"- {e}" for e in sorted(ctx.entities)) or "(none)"
    glossary_block = (
        "\n".join(f"- {k} -> {v}" for k, v in sorted(ctx.glossary.items())) or "(none)"
    )
    return _SYSTEM_TEMPLATE.format(
        source=ctx.source_lang, target=ctx.target_lang,
        entities_block=entities_block, glossary_block=glossary_block,
    )


def _entities_re(entities: Sequence[str]):
    """Case/accent-insensitive alternation over `entities` only -- unlike
    `text.protect.build_protect_re`, no numeric/currency alternatives, so
    it can be used to check entity survival independently of the number
    multiset check."""
    if not entities:
        return None
    variants = set()
    for s in entities:
        variants.add(s)
        variants.add(strip_accents(s))
    parts = [re.escape(s) for s in sorted(variants, key=len, reverse=True)]
    return re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)


def _verify(source: str, english: str, entities: Sequence[str]) -> bool:
    """True if every entity the source actually mentions survived into
    the output (case/accent-insensitively) and the digit-sequence
    multiset is unchanged. Never used to fix or rewrite anything -- a
    failure here only triggers the placeholder-protected retry."""
    entities_re = _entities_re(entities)
    if entities_re is not None:
        mentioned = {strip_accents(m.group(0)).casefold() for m in entities_re.finditer(source)}
        present = strip_accents(english).casefold()
        if any(e not in present for e in mentioned):
            return False
    return Counter(_NUMBER_RE.findall(source)) == Counter(_NUMBER_RE.findall(english))


def _is_missing_credentials(e: Exception) -> bool:
    """`anthropic.Anthropic()` is lenient at construction time -- it only
    resolves credentials (api_key / auth_token / an `ant auth login`
    profile) lazily, on the first real request, and raises a bare
    `TypeError` if none were found. That's neither `APIConnectionError`
    nor `APIStatusError` (no request was ever sent), so it isn't caught
    by the except clauses those satisfy -- without this check it
    propagates all the way up and crashes the whole document instead of
    being recorded as one failed unit. Matched on message text, not just
    `TypeError`, since a TypeError from a real bug in an SDK call's own
    arguments should still surface as a crash, not get silently folded
    into "translation failed"."""
    return isinstance(e, TypeError) and "authentication method" in str(e)


class AnthropicBackend:
    name = "anthropic"
    prefers_batch = True
    uses_placeholder_protection = False

    def __init__(
        self,
        model: str = "claude-opus-5",
        effort: str = "low",
        batch_size: int = 25,
        use_batches_api: bool = False,
        max_retries: int = 5,
        max_output_tokens_per_unit: int = 4096,
        batch_poll_interval: float = 10.0,
        batch_poll_timeout: float = 3600.0,
        client: Any | None = None,
    ):
        """`client`, if given, is used as-is instead of constructing a real
        `anthropic.Anthropic()` -- the only way tests exercise this class
        without either the real package or a network call (see
        `tests/fixtures/fake_anthropic_client.py`). Typed `Any` rather than
        `anthropic.Anthropic` on purpose: the real contract is duck-typed
        (`.messages.create/count_tokens/batches.*`), which is what lets a
        lightweight fake stand in for it in tests."""
        if client is None and anthropic is None:
            raise DependencyError(
                "the 'anthropic' package is required for the Claude backend -- "
                "install with `pip install palimpsest-translate[anthropic]`"
            )
        self.model = model
        self.effort = effort
        self.max_batch = batch_size
        self.use_batches_api = use_batches_api
        self.max_output_tokens_per_unit = max_output_tokens_per_unit
        self.batch_poll_interval = batch_poll_interval
        self.batch_poll_timeout = batch_poll_timeout
        # anthropic.Anthropic() resolves ANTHROPIC_API_KEY (or
        # ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile) from the
        # environment on its own -- never accept a key from config or
        # argv here, so it can never end up in a committed TOML file or a
        # shell history.
        self._client: Any = (
            client if client is not None else anthropic.Anthropic(max_retries=max_retries)
        )

    @classmethod
    def from_config(cls, cfg: AnthropicBackendConfig) -> AnthropicBackend:
        return cls(
            model=cfg.model,
            effort=cfg.effort,
            batch_size=cfg.batch_size,
            use_batches_api=cfg.use_batches_api,
            max_retries=cfg.max_retries,
        )

    # -- single unit ------------------------------------------------------

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        outcome = self._request_one(text, ctx)
        if outcome.status != "ok":
            # A refusal or transport failure isn't fixed by placeholders
            # -- retrying would just repeat it.
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
            # A syntactically well-formed placeholder retry can still have
            # silently DROPPED a token's content rather than mangling its
            # `[[N]]` syntax -- restore()/all_tokens_restored() alone
            # can't see that (a vanished token leaves no stray bracket to
            # detect), so the same entity/number assertion used on the
            # first attempt is run again on the restored text.
            return TranslationResult(
                text=None, status="failed",
                detail="entity/number assertion failed again after the placeholder retry",
            )
        return TranslationResult(text=restored, status="ok")

    def _request_one(self, text: str, ctx: TranslationContext) -> TranslationResult:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens_per_unit,
                system=[{
                    "type": "text",
                    "text": _system_prompt(ctx),
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": _SINGLE_USER_TEMPLATE.format(text=text)}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": _SINGLE_SCHEMA},
                },
            )
        except anthropic.APIConnectionError as e:
            return TranslationResult(text=None, status="failed", detail=str(e))
        except anthropic.APIStatusError as e:
            return TranslationResult(text=None, status="failed", detail=str(e))
        except TypeError as e:
            if not _is_missing_credentials(e):
                raise
            return TranslationResult(
                text=None, status="failed", detail=f"no Anthropic credentials configured: {e}"
            )

        if response.stop_reason == "refusal":
            detail = response.stop_details.category if response.stop_details else None
            return TranslationResult(text=None, status="refused", detail=detail)

        raw = next((b.text for b in response.content if b.type == "text"), None)
        if raw is None:
            return TranslationResult(text=None, status="failed", detail="no text block in response")
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
        if self.use_batches_api:
            return self._translate_batch_async(texts, ctx)
        return self._translate_batch_sync(texts, ctx)

    def _translate_batch_sync(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        units = "\n\n".join(f"[{i}]\n{t}" for i, t in enumerate(texts))
        user = (
            "Translate each of the following paragraphs. Respond with one entry per "
            "paragraph, using the same id.\n\n" + units
        )
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=min(64000, self.max_output_tokens_per_unit * len(texts)),
                system=[{
                    "type": "text",
                    "text": _system_prompt(ctx),
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": _BATCH_SCHEMA},
                },
            )
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            return [
                TranslationResult(text=None, status="failed", detail=str(e)) for _ in texts
            ]
        except TypeError as e:
            if not _is_missing_credentials(e):
                raise
            msg = f"no Anthropic credentials configured: {e}"
            return [TranslationResult(text=None, status="failed", detail=msg) for _ in texts]

        if response.stop_reason == "refusal":
            detail = response.stop_details.category if response.stop_details else None
            return [TranslationResult(text=None, status="refused", detail=detail) for _ in texts]

        raw = next((b.text for b in response.content if b.type == "text"), None)
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

    def _translate_batch_async(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        """Submit `texts` as one job to the async Batches API (50% of
        standard token cost) and poll until it ends. A verification
        failure here is left as "failed" -- `Translator.warm()` falls
        through to `translate()` per failed unit, which does the
        placeholder-retry dance on the synchronous path; duplicating that
        logic here would just be a second copy of the same fallback."""
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        system = [{
            "type": "text",
            "text": _system_prompt(ctx),
            "cache_control": {"type": "ephemeral"},
        }]
        requests = [
            Request(
                custom_id=str(i),
                params=MessageCreateParamsNonStreaming(
                    model=self.model,
                    max_tokens=self.max_output_tokens_per_unit,
                    system=system,  # type: ignore[typeddict-item]
                    messages=[{"role": "user", "content": _SINGLE_USER_TEMPLATE.format(text=t)}],
                    output_config={
                        "effort": self.effort,  # type: ignore[typeddict-item]
                        "format": {"type": "json_schema", "schema": _SINGLE_SCHEMA},
                    },
                ),
            )
            for i, t in enumerate(texts)
        ]

        try:
            batch = self._client.messages.batches.create(requests=requests)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            return [TranslationResult(text=None, status="failed", detail=str(e)) for _ in texts]
        except TypeError as e:
            if not _is_missing_credentials(e):
                raise
            msg = f"no Anthropic credentials configured: {e}"
            return [TranslationResult(text=None, status="failed", detail=msg) for _ in texts]

        deadline = time.monotonic() + self.batch_poll_timeout
        while True:
            batch = self._client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            if time.monotonic() > deadline:
                return [
                    TranslationResult(text=None, status="failed", detail="batch poll timed out")
                    for _ in texts
                ]
            time.sleep(self.batch_poll_interval)

        by_id: dict[int, TranslationResult] = {}
        for item in self._client.messages.batches.results(batch.id):
            i = int(item.custom_id)
            if item.result.type == "succeeded":
                msg = item.result.message
                if msg.stop_reason == "refusal":
                    detail = msg.stop_details.category if msg.stop_details else None
                    by_id[i] = TranslationResult(text=None, status="refused", detail=detail)
                    continue
                raw = next((b.text for b in msg.content if b.type == "text"), None)
                try:
                    english = json.loads(raw)["en"] if raw is not None else None
                except (json.JSONDecodeError, KeyError, TypeError):
                    english = None
                if english is None:
                    by_id[i] = TranslationResult(
                        text=None, status="failed", detail="malformed structured output"
                    )
                elif _verify(texts[i], english, ctx.entities):
                    by_id[i] = TranslationResult(text=english, status="ok")
                else:
                    by_id[i] = TranslationResult(
                        text=None, status="failed", detail="entity/number assertion failed"
                    )
            else:
                by_id[i] = TranslationResult(
                    text=None, status="failed", detail=f"batch item {item.result.type}"
                )

        missing = TranslationResult(text=None, status="failed", detail="missing batch result")
        return [by_id.get(i, missing) for i in range(len(texts))]

    # -- cost ---------------------------------------------------------------

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        pricing = PRICING_USD_PER_MTOK.get(self.model)
        system = _system_prompt(ctx)
        total_input = 0
        try:
            for t in texts:
                counted = self._client.messages.count_tokens(
                    model=self.model,
                    system=system,
                    messages=[{"role": "user", "content": _SINGLE_USER_TEMPLATE.format(text=t)}],
                )
                total_input += counted.input_tokens
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            raise BackendError(f"could not estimate cost: {e}") from e
        except TypeError as e:
            if not _is_missing_credentials(e):
                raise
            raise BackendError(f"no Anthropic credentials configured: {e}") from e
        # Output tokens are unknown until translation happens; translated
        # prose is close in length to source, so input count is used as
        # the output estimate too. Documented as an estimate, not a bound.
        estimated_output = total_input
        usd = None
        if pricing is not None:
            in_rate, out_rate = pricing
            usd = (total_input / 1_000_000) * in_rate + (estimated_output / 1_000_000) * out_rate
        return Cost(input_tokens=total_input, output_tokens=estimated_output, usd=usd)
