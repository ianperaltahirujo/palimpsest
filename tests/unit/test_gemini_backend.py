import pytest

genai = pytest.importorskip("google.genai")

from google.genai import errors as genai_errors  # noqa: E402

from palimpsest.config.model import GeminiBackendConfig  # noqa: E402
from palimpsest.core.errors import BackendError, DependencyError  # noqa: E402
from palimpsest.translate import gemini as gemini_backend  # noqa: E402
from palimpsest.translate.backend import TranslationContext  # noqa: E402
from palimpsest.translate.gemini import GeminiBackend, _verify  # noqa: E402
from tests.fixtures.fake_gemini_client import (  # noqa: E402
    FakeGeminiClient,
    batch_ok_response,
    blocked_response,
    malformed_response,
    ok_response,
)

ENTITIES = ("Grupo Meridian", "Banco Litoral")


def _ctx(**kw) -> TranslationContext:
    return TranslationContext(source_lang="es", target_lang="en", entities=ENTITIES, **kw)


def _api_error(message="server error"):
    return genai_errors.APIError(500, {"error": {"message": message}})


# -- _verify (identical contract to the Anthropic backend's) ----------------

def test_verify_passes_when_entity_and_numbers_survive():
    assert _verify(
        "Grupo Meridian pagó RD$1.234,56 el 5 de enero.",
        "Grupo Meridian paid RD$1.234,56 on January 5.",
        ENTITIES,
    )


def test_verify_fails_when_entity_dropped():
    assert not _verify("Grupo Meridian pagó la deuda.", "The debt was paid.", ENTITIES)


def test_verify_fails_when_number_reformatted():
    assert not _verify("El monto es 1.234,56.", "The amount is 1,234.56.", ENTITIES)


def test_verify_ignores_unmentioned_entities():
    assert _verify("Un texto normal sin nombres.", "A normal text with no names.", ENTITIES)


# -- translate(): happy path ------------------------------------------------

def test_translate_ok_on_first_try():
    client = FakeGeminiClient(responses=[ok_response("Grupo Meridian paid the debt.")])
    backend = GeminiBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "ok"
    assert result.text == "Grupo Meridian paid the debt."
    assert len(client.generate_calls) == 1


def test_translate_sends_system_instruction_with_entities_and_glossary():
    client = FakeGeminiClient(responses=[ok_response("hello")])
    backend = GeminiBackend(client=client)
    backend.translate("hola", _ctx(glossary={"Fideicomiso": "Trust"}))
    config = client.generate_calls[0]["config"]
    assert "Grupo Meridian" in config.system_instruction
    assert "Fideicomiso -> Trust" in config.system_instruction


# -- translate(): verification-failure retry --------------------------------

def test_translate_retries_with_placeholders_when_entity_dropped():
    client = FakeGeminiClient(
        responses=[
            ok_response("The debt was paid."),
            ok_response("[[0]] paid the debt."),
        ]
    )
    backend = GeminiBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "ok"
    assert result.text == "Grupo Meridian paid the debt."
    assert len(client.generate_calls) == 2
    assert "[[0]]" in client.generate_calls[1]["contents"]


def test_translate_fails_when_placeholder_retry_also_fails_verification():
    client = FakeGeminiClient(
        responses=[
            ok_response("The debt was paid."),
            ok_response("The debt was paid."),
        ]
    )
    backend = GeminiBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "failed"
    assert result.text is None


# -- translate(): safety block -----------------------------------------------

def test_translate_block_is_not_retried():
    client = FakeGeminiClient(responses=[blocked_response(reason="SAFETY")])
    backend = GeminiBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "refused"
    assert result.detail == "SAFETY"
    assert len(client.generate_calls) == 1


def test_translate_empty_candidates_without_block_reason_is_refused():
    client = FakeGeminiClient(responses=[blocked_response(reason=None)])
    backend = GeminiBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "refused"


# -- translate(): transport / parsing failures -------------------------------

def test_translate_transport_failure_is_failed_status():
    client = FakeGeminiClient(raise_on_generate=_api_error("rate limited"))
    backend = GeminiBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "failed"


def test_translate_malformed_json_is_failed_status():
    client = FakeGeminiClient(responses=[malformed_response("not json")])
    backend = GeminiBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "failed"
    assert "malformed" in (result.detail or "")


# -- translate_batch() -------------------------------------------------------

def test_translate_batch_empty_returns_empty():
    backend = GeminiBackend(client=FakeGeminiClient())
    assert backend.translate_batch([], _ctx()) == []


def test_translate_batch_matches_by_id_not_position():
    client = FakeGeminiClient(responses=[batch_ok_response({1: "second", 0: "first"})])
    backend = GeminiBackend(client=client)
    results = backend.translate_batch(["uno", "dos"], _ctx())
    assert [r.status for r in results] == ["ok", "ok"]
    assert [r.text for r in results] == ["first", "second"]


def test_translate_batch_missing_id_is_failed():
    client = FakeGeminiClient(responses=[batch_ok_response({0: "first"})])
    backend = GeminiBackend(client=client)
    results = backend.translate_batch(["uno", "dos"], _ctx())
    assert results[0].status == "ok"
    assert results[1].status == "failed"


def test_translate_batch_verification_failure_is_failed():
    client = FakeGeminiClient(responses=[batch_ok_response({0: "The debt was paid."})])
    backend = GeminiBackend(client=client)
    results = backend.translate_batch(["Grupo Meridian pagó la deuda."], _ctx())
    assert results[0].status == "failed"


def test_translate_batch_block_marks_all_units_refused():
    client = FakeGeminiClient(responses=[blocked_response()])
    backend = GeminiBackend(client=client)
    results = backend.translate_batch(["uno", "dos", "tres"], _ctx())
    assert [r.status for r in results] == ["refused", "refused", "refused"]


# -- estimate() ---------------------------------------------------------------

def test_estimate_sums_tokens_and_prices_known_model():
    client = FakeGeminiClient(tokens_per_call=1_000_000)
    backend = GeminiBackend(client=client, model="gemini-2.5-flash-lite")
    cost = backend.estimate(["uno", "dos"], _ctx())
    assert cost is not None
    assert cost.input_tokens == 2_000_000
    assert cost.usd == pytest.approx(2 * 0.10 + 2 * 0.40)


def test_estimate_returns_none_usd_for_unknown_model():
    client = FakeGeminiClient(tokens_per_call=100)
    backend = GeminiBackend(client=client, model="gemini-some-future-model")
    cost = backend.estimate(["uno"], _ctx())
    assert cost is not None
    assert cost.usd is None


def test_estimate_raises_backend_error_on_transport_failure():
    client = FakeGeminiClient()
    backend = GeminiBackend(client=client)

    def _boom(**kwargs):
        raise _api_error("count failed")

    client.models.count_tokens = _boom
    with pytest.raises(BackendError):
        backend.estimate(["uno"], _ctx())


# -- construction -------------------------------------------------------------

def test_dependency_error_when_no_client_and_package_missing(monkeypatch):
    monkeypatch.setattr(gemini_backend, "genai", None)
    with pytest.raises(DependencyError):
        GeminiBackend()


def test_dependency_error_when_no_client_and_no_api_key(monkeypatch):
    """genai.Client() raises ValueError immediately if neither
    GEMINI_API_KEY nor GOOGLE_API_KEY is set (unlike anthropic.Anthropic(),
    which is lenient until the first real call) -- this must surface as
    the same clean DependencyError as a missing package, not a raw SDK
    ValueError with no actionable message."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(DependencyError, match="GEMINI_API_KEY"):
        GeminiBackend()


def test_from_config_maps_fields(monkeypatch):
    # genai.Client() raises ValueError if no GEMINI_API_KEY/GOOGLE_API_KEY
    # is set in the environment (unlike anthropic.Anthropic(), which is
    # lenient until the first real call) -- from_config() doesn't take a
    # client override, so the real constructor is stubbed instead of
    # relying on CI happening to have a key configured.
    monkeypatch.setattr(gemini_backend.genai, "Client", lambda: FakeGeminiClient())
    cfg = GeminiBackendConfig(
        model="gemini-3.6-flash", batch_size=10, max_output_tokens_per_unit=2048,
    )
    backend = GeminiBackend.from_config(cfg)
    assert backend.model == "gemini-3.6-flash"
    assert backend.max_batch == 10
    assert backend.max_output_tokens_per_unit == 2048
