"""Cost estimation for `--dry-run`.

Aggregates `Backend.estimate()` over a corpus of paragraphs, chunked the
same way `Translator.warm()` chunks them (respecting `backend.max_batch`
for a batching backend), and turns the result into a human-readable
summary.

`Backend.estimate()` returns `None` per call for two different reasons --
the backend is free (Google), or it just can't price this particular
request (an Anthropic model missing from `PRICING_USD_PER_MTOK`). Either
way, `None` must never be silently folded into a `0.0` total: that would
be exactly the "a failure masquerades as a result" bug `translate.cache`
exists to prevent, one layer up, for a dry-run cost report instead of a
translation. `CorpusEstimate.usd` stays `None` unless at least one chunk
was actually priced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from palimpsest.translate.backend import Backend, TranslationContext
from palimpsest.translate.cache import Cache


@dataclass(frozen=True)
class CorpusEstimate:
    unit_count: int
    priced_unit_count: int
    """How many of `unit_count` paragraphs fell in a chunk the backend was
    actually able to price -- may be less than `unit_count` if pricing
    failed partway through a corpus."""
    input_tokens: int
    output_tokens: int
    usd: float | None
    """None unless at least one chunk was priced with a known $/token
    rate -- never coerced to 0.0 for "free or unknown"."""


def estimate_corpus(
    texts: Sequence[str], backend: Backend, ctx: TranslationContext
) -> CorpusEstimate:
    batch_size = backend.max_batch if backend.prefers_batch else 1
    input_tokens = 0
    output_tokens = 0
    usd_total = 0.0
    priced_usd = False
    priced_units = 0

    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        cost = backend.estimate(chunk, ctx)
        if cost is None:
            continue
        input_tokens += cost.input_tokens
        output_tokens += cost.output_tokens
        priced_units += len(chunk)
        if cost.usd is not None:
            usd_total += cost.usd
            priced_usd = True

    return CorpusEstimate(
        unit_count=len(texts),
        priced_unit_count=priced_units,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=usd_total if priced_usd else None,
    )


def format_estimate(estimate: CorpusEstimate) -> str:
    lines = [f"{estimate.unit_count} paragraph(s)"]
    if estimate.priced_unit_count < estimate.unit_count:
        lines.append(
            f"  priced {estimate.priced_unit_count}/{estimate.unit_count} "
            "(backend could not estimate the rest)"
        )
    if estimate.input_tokens or estimate.output_tokens:
        lines.append(
            f"  ~{estimate.input_tokens:,} input tokens, ~{estimate.output_tokens:,} output tokens"
        )
    if estimate.usd is not None:
        lines.append(f"  ~${estimate.usd:,.2f} estimated")
    else:
        lines.append("  cost: unknown (backend is free, or could not price this model)")
    return "\n".join(lines)


@dataclass(frozen=True)
class DocumentEstimate:
    """The five numbers the CLI's `--dry-run` prints and the web
    Estimate screen shows, computed once here so both stay in sync by
    construction rather than by two independently-maintained call sites."""

    rel: str
    kind: str | None
    """PDF classification (digital/scan/ocr), or None for an Office
    document, which has no such classification."""
    pages: int | None
    """None for Office documents -- "pages" isn't a meaningful count for
    a spreadsheet or slide deck the way it is for a PDF."""
    unit_count: int
    """Total paragraphs/strings found, including duplicates."""
    unique_count: int
    cache_hits: int
    corpus: CorpusEstimate
    """Priced only over the unique strings NOT already in cache -- see
    `estimate_document`."""


def estimate_document(
    rel: str,
    texts: Sequence[str],
    backend: Backend,
    ctx: TranslationContext,
    cache: Cache,
    kind: str | None = None,
    pages: int | None = None,
) -> DocumentEstimate:
    """`texts` is every extracted paragraph/string for this document,
    duplicates included -- this function does the deduplication and the
    cache-hit split itself, so every caller (CLI, server) computes the
    same numbers the same way."""
    unique = list(dict.fromkeys(texts))
    hits = sum(1 for t in unique if cache.get_ok(t) is not None)
    to_price = [t for t in unique if cache.get_ok(t) is None]
    corpus = estimate_corpus(to_price, backend, ctx)
    return DocumentEstimate(
        rel=rel, kind=kind, pages=pages,
        unit_count=len(texts), unique_count=len(unique), cache_hits=hits,
        corpus=corpus,
    )


def format_document_estimate(est: DocumentEstimate) -> str:
    lines = [f"[{est.rel}]" + (f" kind={est.kind}" if est.kind else "")]
    if est.pages is not None:
        lines.append(f"  pages: {est.pages}")
    label = "paragraphs" if est.pages is not None else "strings"
    lines.append(f"  {label}: {est.unit_count} ({est.unique_count} unique)")
    if est.unique_count:
        pct = 100 * est.cache_hits / est.unique_count
        lines.append(f"  cache hits: {est.cache_hits}/{est.unique_count} ({pct:.0f}%)")
    lines.extend(format_estimate(est.corpus).splitlines())
    return "\n".join(lines)
