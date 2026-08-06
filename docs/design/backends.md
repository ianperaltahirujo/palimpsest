# Translation backends

palimpsest ships two backends behind one `Backend` protocol
(`palimpsest.translate.backend`): Google (free, phrase-level) and Claude
(paid, LLM). `[backend].name` in `palimpsest.toml` selects the default;
`[backend].fallback` names a second backend to fall back to. This document
explains why they work differently internally, not just how to configure
them -- see `docs/configuration.md` for the TOML reference.

## Google

`translate/google.py`, via `deep_translator`'s scrape of the free web
endpoint. No API key, no cost, no SLA -- an undocumented endpoint that can
rate-limit or change shape without notice. Good as the zero-setup default
and as a fallback behind a paid backend; not recommended as the only
backend for a production corpus run.

Google is a bare phrase-level API: it has no concept of "this is a
protected entity" or "translate this term this way." `uses_placeholder_protection
= True` -- `Translator` compensates by replacing every protected entity and
number with a `[[N]]` placeholder before the call and restoring the
originals afterward (`text.protect`). This is the *only* way to guarantee
verbatim survival with a backend that can't be told to preserve anything.

## Claude (Anthropic)

`translate/anthropic.py`, via the `anthropic` Python SDK (`palimpsest[anthropic]`
extra). Default model `claude-opus-5`. Credentials come from the
`ANTHROPIC_API_KEY` environment variable only -- never from `palimpsest.toml`
or a CLI flag, so a key can never end up committed or in shell history.

### Why placeholders are off for this backend

`uses_placeholder_protection = False`. An LLM can be handed the entity list
and glossary directly and asked to honor them, and it reads the whole
sentence -- placeholdering every number in a financial-statement line
(`[[0]] [[1]] [[2]] [[3]]`) would destroy exactly the context that makes it
translate well in the first place.

So protection here is an **assertion, not a transformation**. The system
prompt carries the entity list and glossary and instructs Claude not to
reformat numbers (Spanish `1.234,56` must stay `1.234,56`, not become
`1,234.56` -- see below for why that instruction matters). After every
response, `_verify()` checks mechanically that:

1. every entity the source actually mentions is still present,
   case/accent-insensitively, in the output, and
2. the source and output contain the exact same multiset of digit-sequence
   tokens (`\d[\d.,]*`).

If either check fails, the unit is retried exactly once using the same
`[[N]]` placeholder scheme the Google backend always uses -- proven,
tested, and guaranteed to preserve the token verbatim -- rather than
shipping a translation that silently dropped or altered content. If the
retry's *restored* text still fails the same assertion (the model dropped
the placeholder's content entirely rather than mangling its `[[N]]`
syntax, which the placeholder mechanism alone can't detect), the unit is
marked `status="failed"` and ships as the original Spanish, per the
honest-cache contract in `translate/cache.py`.

**Why "don't reformat numbers" is part of the prompt, not just a nice-to-have:**
the verification check is a literal string comparison of digit-sequence
tokens. If Claude "helpfully" converted Spanish number punctuation to
English convention, every financial paragraph would trip the assertion and
fall back to the placeholder retry -- correct in outcome (numbers still
survive) but wasteful. Instructing Claude to leave punctuation alone keeps
the fast path fast, and keeps output consistent with the Google backend,
which never reformats numbers either (they're never touched -- they travel
as opaque `[[N]]` tokens).

### Refusals

`stop_reason == "refusal"` maps to a `TranslationResult(status="refused")`,
distinct from `"failed"` in `translate/cache.py`'s cache-status contract: a
refusal isn't a transient error, and a placeholder retry will not fix a
policy decline, so none is attempted.

### Prompt caching

The system prompt (role, entity list, glossary table) carries
`cache_control: {"type": "ephemeral"}`. It is built deterministically --
entities and glossary entries are sorted before rendering -- so identical
configuration always produces byte-identical system-prompt text, which is
required both for the cache to ever hit and for `translate/cache.py`'s
`compute_namespace()` to correctly detect when configuration has actually
changed. See `docs/configuration.md` for how a changed entity list or
glossary shows up as a new cache namespace rather than silently mixing
with old output.

### Batching

`translate_batch()` sends one structured-output request per chunk
(`[backend.anthropic].batch_size` paragraphs, default 25), with a JSON
schema requiring an explicit `id` field per translated unit -- results are
matched strictly by `id`, never by list position, so a model that skips or
reorders a unit can't silently shift every later item off by one.

With `[backend.anthropic].use_batches_api = true`, the same chunk is
submitted to the async Message Batches API instead (50% of standard token
cost; results typically within an hour, up to 24h) and polled until
complete. A verification failure on an individual unit is left as
`"failed"` rather than retried inline -- `Translator.warm()` already falls
through to `translate()` for any non-`"ok"` batch result, which does the
full placeholder-retry dance on the synchronous path, so duplicating that
logic inside the batch path would just be a second copy of the same
fallback.

## Cost

Pricing cached **2026-06-24** (via the `claude-api` skill's current model
table at the time this backend was built) -- Anthropic's pricing page is
the source of truth if this drifts:

| Model | Input $/MTok | Output $/MTok |
|---|---:|---:|
| `claude-opus-5` (default) | $5.00 | $25.00 |
| `claude-sonnet-5` | $3.00 ($2.00 intro through 2026-08-31) | $15.00 ($10.00 intro) |
| `claude-haiku-4-5` | $1.00 | $5.00 |

`AnthropicBackend.estimate()` calls `messages.count_tokens()` per unit (an
accurate, model-specific count -- never approximated with a generic
tokenizer) to project input cost; output cost is estimated as equal to
input cost, since translated prose is close in length to source and there
is no ground truth before translation actually happens. `--dry-run`
(`translate/estimate.py`) aggregates this across a whole corpus and reports
cost as unknown, not zero, for any backend or model it can't price --
Google is free by design, and an unrecognized model string simply isn't in
the table above.

## Choosing a model

Legal and financial documents are the kind of high-stakes, easy-to-get-subtly-wrong
translation work that benefits from the strongest available model, so
`claude-opus-5` is the default rather than a cheaper model chosen to
minimize per-page cost. `claude-sonnet-5` is the reasonable choice for a
large corpus where cost matters more than the last few percent of quality;
`claude-haiku-4-5` is not recommended for this document type at all --
it's sized for high-volume, low-stakes text, not for content whose whole
premise is "the numbers and names must not move."
