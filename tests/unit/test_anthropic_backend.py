import httpx
import pytest

anthropic = pytest.importorskip("anthropic")

from palimpsest.config.model import AnthropicBackendConfig
from palimpsest.core.errors import BackendError, DependencyError
from palimpsest.translate import anthropic as anthropic_backend
from palimpsest.translate.anthropic import AnthropicBackend, _verify
from palimpsest.translate.backend import TranslationContext
from tests.fixtures.fake_anthropic_client import (
    BatchErrored,
    BatchResultItem,
    BatchSucceeded,
    FakeAnthropicClient,
    batch_ok_message,
    malformed_message,
    ok_message,
    refused_message,
)

ENTITIES = ("Grupo Meridian", "Banco Litoral")


def _ctx(**kw) -> TranslationContext:
    return TranslationContext(source_lang="es", target_lang="en", entities=ENTITIES, **kw)


def _status_error(message="server error"):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(500, request=req)
    return anthropic.APIStatusError(message, response=resp, body=None)


def _connection_error():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=req)


# -- _verify --------------------------------------------------------------

def test_verify_passes_when_entity_and_numbers_survive():
    assert _verify(
        "Grupo Meridian pagó RD$1.234,56 el 5 de enero.",
        "Grupo Meridian paid RD$1.234,56 on January 5.",
        ENTITIES,
    )


def test_verify_fails_when_entity_dropped():
    assert not _verify(
        "Grupo Meridian pagó la deuda.",
        "The debt was paid.",
        ENTITIES,
    )


def test_verify_fails_when_number_reformatted():
    """Spanish 1.234,56 becoming English-formatted 1,234.56 changes the
    literal digit-sequence token even though the value is unchanged --
    this is deliberate (see anthropic.py's module docstring): the system
    prompt instructs Claude not to reformat, so a mismatch here is a real
    instruction-following failure worth retrying, not a false positive."""
    assert not _verify("El monto es 1.234,56.", "The amount is 1,234.56.", ENTITIES)


def test_verify_ignores_unmentioned_entities():
    assert _verify("Un texto normal sin nombres.", "A normal text with no names.", ENTITIES)


# -- translate(): happy path ------------------------------------------------

def test_translate_ok_on_first_try():
    client = FakeAnthropicClient(responses=[ok_message("Grupo Meridian paid the debt.")])
    backend = AnthropicBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "ok"
    assert result.text == "Grupo Meridian paid the debt."
    assert len(client.create_calls) == 1


def test_translate_sends_cached_system_prompt_with_entities_and_glossary():
    client = FakeAnthropicClient(responses=[ok_message("hello")])
    backend = AnthropicBackend(client=client)
    backend.translate("hola", _ctx(glossary={"Fideicomiso": "Trust"}))
    system = client.create_calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "Grupo Meridian" in system[0]["text"]
    assert "Fideicomiso -> Trust" in system[0]["text"]


# -- translate(): verification-failure retry --------------------------------

def test_translate_retries_with_placeholders_when_entity_dropped():
    client = FakeAnthropicClient(
        responses=[
            ok_message("The debt was paid."),  # drops "Grupo Meridian" -- fails verify
            ok_message("[[0]] paid the debt."),  # protected retry: placeholder preserved
        ]
    )
    backend = AnthropicBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "ok"
    assert result.text == "Grupo Meridian paid the debt."
    assert len(client.create_calls) == 2
    # second call was sent the placeholdered text, not the original
    assert "[[0]]" in client.create_calls[1]["messages"][0]["content"]


def test_translate_fails_when_placeholder_retry_also_fails_verification():
    client = FakeAnthropicClient(
        responses=[
            ok_message("The debt was paid."),
            ok_message("The debt was paid."),  # placeholder retry also drops [[0]]
        ]
    )
    backend = AnthropicBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "failed"
    assert result.text is None


# -- translate(): refusal ----------------------------------------------------

def test_translate_refusal_is_not_retried():
    client = FakeAnthropicClient(responses=[refused_message(category="cyber")])
    backend = AnthropicBackend(client=client)
    result = backend.translate("Grupo Meridian pagó la deuda.", _ctx())
    assert result.status == "refused"
    assert result.detail == "cyber"
    assert len(client.create_calls) == 1  # no placeholder retry attempted


# -- translate(): transport / parsing failures -------------------------------

def test_translate_transport_failure_is_failed_status():
    client = FakeAnthropicClient(raise_on_create=_status_error("rate limited"))
    backend = AnthropicBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "failed"
    assert "rate limited" in (result.detail or "")


def test_translate_connection_error_is_failed_status():
    client = FakeAnthropicClient(raise_on_create=_connection_error())
    backend = AnthropicBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "failed"


def test_translate_malformed_json_is_failed_status():
    client = FakeAnthropicClient(responses=[malformed_message("not json")])
    backend = AnthropicBackend(client=client)
    result = backend.translate("hola", _ctx())
    assert result.status == "failed"
    assert "malformed" in (result.detail or "")


# -- translate_batch(): sync path --------------------------------------------

def test_translate_batch_empty_returns_empty():
    backend = AnthropicBackend(client=FakeAnthropicClient())
    assert backend.translate_batch([], _ctx()) == []


def test_translate_batch_sync_matches_by_id_not_position():
    client = FakeAnthropicClient(
        responses=[batch_ok_message({1: "second", 0: "first"})]  # out of order on purpose
    )
    backend = AnthropicBackend(client=client)
    results = backend.translate_batch(["uno", "dos"], _ctx())
    assert [r.status for r in results] == ["ok", "ok"]
    assert [r.text for r in results] == ["first", "second"]


def test_translate_batch_sync_missing_id_is_failed():
    client = FakeAnthropicClient(responses=[batch_ok_message({0: "first"})])
    backend = AnthropicBackend(client=client)
    results = backend.translate_batch(["uno", "dos"], _ctx())
    assert results[0].status == "ok"
    assert results[1].status == "failed"


def test_translate_batch_sync_verification_failure_is_failed():
    client = FakeAnthropicClient(
        responses=[batch_ok_message({0: "The debt was paid."})]  # drops the entity
    )
    backend = AnthropicBackend(client=client)
    results = backend.translate_batch(["Grupo Meridian pagó la deuda."], _ctx())
    assert results[0].status == "failed"


def test_translate_batch_sync_refusal_marks_all_units_refused():
    client = FakeAnthropicClient(responses=[refused_message()])
    backend = AnthropicBackend(client=client)
    results = backend.translate_batch(["uno", "dos", "tres"], _ctx())
    assert [r.status for r in results] == ["refused", "refused", "refused"]


# -- translate_batch(): async Batches API path -------------------------------

def test_translate_batch_via_batches_api_maps_by_custom_id():
    client = FakeAnthropicClient(
        batch_results=[
            BatchResultItem(custom_id="1", result=BatchSucceeded(message=ok_message("second"))),
            BatchResultItem(custom_id="0", result=BatchSucceeded(message=ok_message("first"))),
        ]
    )
    backend = AnthropicBackend(client=client, use_batches_api=True)
    results = backend.translate_batch(["uno", "dos"], _ctx())
    assert [r.text for r in results] == ["first", "second"]


def test_translate_batch_via_batches_api_polls_until_ended():
    client = FakeAnthropicClient(
        batch_results=[
            BatchResultItem(custom_id="0", result=BatchSucceeded(message=ok_message("uno")))
        ],
        batch_status_sequence=["in_progress", "in_progress", "ended"],
    )
    backend = AnthropicBackend(client=client, use_batches_api=True, batch_poll_interval=0)
    results = backend.translate_batch(["hola"], _ctx())
    assert results[0].status == "ok"


def test_translate_batch_via_batches_api_errored_item_is_failed():
    client = FakeAnthropicClient(
        batch_results=[BatchResultItem(custom_id="0", result=BatchErrored())]
    )
    backend = AnthropicBackend(client=client, use_batches_api=True)
    results = backend.translate_batch(["hola"], _ctx())
    assert results[0].status == "failed"


def test_translate_batch_via_batches_api_refusal_item_maps_to_refused():
    client = FakeAnthropicClient(
        batch_results=[
            BatchResultItem(custom_id="0", result=BatchSucceeded(message=refused_message()))
        ]
    )
    backend = AnthropicBackend(client=client, use_batches_api=True)
    results = backend.translate_batch(["hola"], _ctx())
    assert results[0].status == "refused"


# -- estimate() ---------------------------------------------------------------

def test_estimate_sums_tokens_and_prices_known_model():
    client = FakeAnthropicClient(tokens_per_call=1_000_000)
    backend = AnthropicBackend(client=client, model="claude-opus-5")
    cost = backend.estimate(["uno", "dos"], _ctx())
    assert cost is not None
    assert cost.input_tokens == 2_000_000
    # 2M input @ $5/MTok + 2M output @ $25/MTok (output estimated == input)
    assert cost.usd == pytest.approx(2 * 5.00 + 2 * 25.00)


def test_estimate_returns_none_usd_for_unknown_model():
    client = FakeAnthropicClient(tokens_per_call=100)
    backend = AnthropicBackend(client=client, model="claude-some-future-model")
    cost = backend.estimate(["uno"], _ctx())
    assert cost is not None
    assert cost.usd is None


def test_estimate_raises_backend_error_on_transport_failure():
    client = FakeAnthropicClient()
    backend = AnthropicBackend(client=client)

    def _boom(**kwargs):
        raise _status_error("count failed")

    client.messages.count_tokens = _boom
    with pytest.raises(BackendError):
        backend.estimate(["uno"], _ctx())


# -- construction -------------------------------------------------------------

def test_dependency_error_when_no_client_and_package_missing(monkeypatch):
    monkeypatch.setattr(anthropic_backend, "anthropic", None)
    with pytest.raises(DependencyError):
        AnthropicBackend()


def test_from_config_maps_fields():
    cfg = AnthropicBackendConfig(
        model="claude-sonnet-5", effort="high", batch_size=10,
        use_batches_api=True, max_retries=1,
    )
    backend = AnthropicBackend.from_config(cfg)
    assert backend.model == "claude-sonnet-5"
    assert backend.effort == "high"
    assert backend.max_batch == 10
    assert backend.use_batches_api is True
