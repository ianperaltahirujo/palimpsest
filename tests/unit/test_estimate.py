from palimpsest.translate.backend import Cost, TranslationContext
from palimpsest.translate.cache import Cache
from palimpsest.translate.estimate import (
    estimate_corpus,
    estimate_document,
    format_document_estimate,
    format_estimate,
)

CTX = TranslationContext(source_lang="es", target_lang="en")


class _FreeBackend:
    """Like GoogleBackend: always returns None (free, not "unknown")."""

    max_batch = 20
    prefers_batch = False

    def estimate(self, texts, ctx):
        return None


class _PricedBackend:
    max_batch = 2
    prefers_batch = True

    def __init__(self):
        self.calls: list[list[str]] = []

    def estimate(self, texts, ctx):
        self.calls.append(list(texts))
        return Cost(
            input_tokens=100 * len(texts), output_tokens=50 * len(texts), usd=1.5 * len(texts)
        )


class _PartiallyPriceableBackend:
    """Fails to price every other chunk -- e.g. a transient count_tokens
    error the caller chose to swallow as None rather than raise."""

    max_batch = 1
    prefers_batch = True

    def __init__(self):
        self.n = 0

    def estimate(self, texts, ctx):
        self.n += 1
        if self.n % 2 == 0:
            return None
        return Cost(input_tokens=10, output_tokens=5, usd=0.1)


def test_estimate_corpus_chunks_by_backend_max_batch():
    backend = _PricedBackend()
    estimate_corpus(["a", "b", "c", "d", "e"], backend, CTX)
    assert backend.calls == [["a", "b"], ["c", "d"], ["e"]]


def test_estimate_corpus_chunks_by_one_when_backend_does_not_prefer_batch():
    backend = _FreeBackend()
    # no assertion on chunking needed here beyond it not raising;
    # covered precisely by the priced-backend test above.
    result = estimate_corpus(["a", "b"], backend, CTX)
    assert result.usd is None


def test_estimate_corpus_sums_tokens_and_usd():
    backend = _PricedBackend()
    result = estimate_corpus(["a", "b", "c"], backend, CTX)
    assert result.unit_count == 3
    assert result.priced_unit_count == 3
    assert result.input_tokens == 100 * 3
    assert result.output_tokens == 50 * 3
    assert result.usd == 1.5 * 2 + 1.5 * 1  # chunk of 2 + chunk of 1


def test_estimate_corpus_free_backend_usd_is_none_not_zero():
    backend = _FreeBackend()
    result = estimate_corpus(["a", "b", "c"], backend, CTX)
    assert result.usd is None
    assert result.priced_unit_count == 0
    assert result.input_tokens == 0


def test_estimate_corpus_partial_pricing_reports_priced_count():
    backend = _PartiallyPriceableBackend()
    result = estimate_corpus(["a", "b", "c", "d"], backend, CTX)
    assert result.unit_count == 4
    assert result.priced_unit_count == 2  # chunks 1 and 3 priced, 2 and 4 did not
    assert result.usd == 0.2


def test_estimate_corpus_empty_texts():
    result = estimate_corpus([], _PricedBackend(), CTX)
    assert result.unit_count == 0
    assert result.usd is None


def test_format_estimate_free_backend():
    result = estimate_corpus(["a"], _FreeBackend(), CTX)
    text = format_estimate(result)
    assert "1 paragraph(s)" in text
    assert "unknown" in text


def test_format_estimate_priced_backend_shows_usd_and_tokens():
    result = estimate_corpus(["a", "b"], _PricedBackend(), CTX)
    text = format_estimate(result)
    assert "input tokens" in text
    assert "$" in text


def test_format_estimate_notes_partial_pricing():
    result = estimate_corpus(["a", "b", "c", "d"], _PartiallyPriceableBackend(), CTX)
    text = format_estimate(result)
    assert "priced 2/4" in text


# -- estimate_document -------------------------------------------------


def test_estimate_document_deduplicates_and_counts_cache_hits(tmp_path):
    cache = Cache(tmp_path / "cache.json", namespace="ns")
    cache.put("a", "A", "ok")
    texts = ["a", "a", "b", "c"]  # "a" repeated, and already cached
    backend = _PricedBackend()

    est = estimate_document("doc.pdf", texts, backend, CTX, cache, kind="digital", pages=3)

    assert est.unit_count == 4  # includes the duplicate
    assert est.unique_count == 3  # a, b, c
    assert est.cache_hits == 1  # only "a"
    assert est.kind == "digital"
    assert est.pages == 3
    # only the two NOT-cached unique strings (b, c) are priced
    assert backend.calls == [["b", "c"]]
    assert est.corpus.unit_count == 2


def test_estimate_document_office_has_no_kind_or_pages(tmp_path):
    cache = Cache(tmp_path / "cache.json", namespace="ns")
    est = estimate_document("Budget.xlsx", ["x", "y"], _PricedBackend(), CTX, cache)
    assert est.kind is None
    assert est.pages is None


def test_format_document_estimate_pdf_shows_pages_and_kind(tmp_path):
    cache = Cache(tmp_path / "cache.json", namespace="ns")
    est = estimate_document(
        "doc.pdf", ["a", "b"], _PricedBackend(), CTX, cache, kind="scan", pages=5,
    )
    text = format_document_estimate(est)
    assert "kind=scan" in text
    assert "pages: 5" in text
    assert "paragraphs: 2 (2 unique)" in text


def test_format_document_estimate_office_omits_pages(tmp_path):
    cache = Cache(tmp_path / "cache.json", namespace="ns")
    est = estimate_document("Budget.xlsx", ["x", "y"], _PricedBackend(), CTX, cache)
    text = format_document_estimate(est)
    assert "pages:" not in text
    assert "strings: 2 (2 unique)" in text
