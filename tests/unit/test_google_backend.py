"""No test here makes a real network call -- deep_translator's Google
endpoint is an undocumented scrape with no SLA. GoogleBackend's OWN retry/
error-handling logic is tested by injecting a fake stand-in directly into
its translator cache, bypassing the real GoogleTranslator construction
and network call entirely.
"""

from palimpsest.translate.backend import TranslationContext
from palimpsest.translate.google import GoogleBackend

CTX = TranslationContext(source_lang="es", target_lang="en")


class _StubTranslator:
    """Stands in for deep_translator.GoogleTranslator."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def translate(self, text):
        self.calls.append(text)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def translate_batch(self, texts):
        self.batch_calls.append(list(texts))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _backend_with_stub(responses) -> tuple[GoogleBackend, _StubTranslator]:
    backend = GoogleBackend(attempts=3, retry_pause=0.0)
    stub = _StubTranslator(responses)
    backend._translators[("es", "en")] = stub
    return backend, stub


def test_static_interface_shape():
    backend = GoogleBackend()
    assert backend.name == "google"
    assert backend.uses_placeholder_protection is True
    assert backend.prefers_batch is False
    assert backend.max_batch == 20


def test_estimate_is_free():
    backend = GoogleBackend()
    assert backend.estimate(["hola"], CTX) is None


def test_translate_success_first_attempt():
    backend, stub = _backend_with_stub(["Hello"])
    result = backend.translate("Hola", CTX)
    assert result.status == "ok"
    assert result.text == "Hello"
    assert stub.calls == ["Hola"]


def test_translate_retries_on_exception_then_succeeds():
    backend, stub = _backend_with_stub([RuntimeError("transient"), "Hello"])
    result = backend.translate("Hola", CTX)
    assert result.status == "ok"
    assert result.text == "Hello"
    assert len(stub.calls) == 2


def test_translate_fails_after_exhausting_attempts():
    backend, stub = _backend_with_stub(
        [RuntimeError("a"), RuntimeError("b"), RuntimeError("c")]
    )
    result = backend.translate("Hola", CTX)
    assert result.status == "failed"
    assert result.text is None
    assert result.detail == "c"
    assert len(stub.calls) == 3


def test_translate_treats_empty_response_as_failure_with_retry():
    backend, stub = _backend_with_stub(["", "Hello"])
    result = backend.translate("Hola", CTX)
    assert result.status == "ok"
    assert result.text == "Hello"


def test_translate_batch_success():
    backend, _stub = _backend_with_stub([["Hello", "World"]])
    results = backend.translate_batch(["Hola", "Mundo"], CTX)
    assert [r.status for r in results] == ["ok", "ok"]
    assert [r.text for r in results] == ["Hello", "World"]


def test_translate_batch_exception_fails_every_item():
    backend, _stub = _backend_with_stub([RuntimeError("batch broke")])
    results = backend.translate_batch(["Hola", "Mundo"], CTX)
    assert len(results) == 2
    assert all(r.status == "failed" for r in results)


def test_translate_batch_empty_item_marked_failed_individually():
    backend, _stub = _backend_with_stub([["Hello", ""]])
    results = backend.translate_batch(["Hola", "Mundo"], CTX)
    assert results[0].status == "ok"
    assert results[1].status == "failed"


def test_separate_language_pairs_get_separate_translator_instances():
    backend = GoogleBackend()
    ctx_es_en = TranslationContext(source_lang="es", target_lang="en")
    ctx_fr_en = TranslationContext(source_lang="fr", target_lang="en")
    t1 = backend._translator_for(ctx_es_en)
    t2 = backend._translator_for(ctx_fr_en)
    t1_again = backend._translator_for(ctx_es_en)
    assert t1 is not t2
    assert t1 is t1_again
