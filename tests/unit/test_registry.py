import pytest

from palimpsest.config.model import (
    BackendConfig,
    Config,
    GeminiBackendConfig,
    GoogleBackendConfig,
    PathsConfig,
)
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import TranslationContext, TranslationResult
from palimpsest.translate.google import GoogleBackend
from palimpsest.translate.registry import FallbackBackend, build_translator, make_backend
from palimpsest.translate.translator import Translator
from tests.fixtures.fake_backend import FailingBackend, FakeBackend

CTX = TranslationContext(source_lang="es", target_lang="en", entities=("Grupo Meridian",))


def _config(name="google", fallback=None) -> Config:
    return Config(backend=BackendConfig(name=name, fallback=fallback))


def test_make_backend_google_only():
    backend = make_backend(_config(name="google", fallback=None))
    assert isinstance(backend, GoogleBackend)


def test_make_backend_wires_google_config_fields():
    cfg = Config(
        backend=BackendConfig(
            name="google", fallback=None,
            google=GoogleBackendConfig(batch_size=7, pause_seconds=0.1),
        )
    )
    backend = make_backend(cfg)
    assert backend.max_batch == 7
    assert backend.retry_pause == 0.1


def test_make_backend_no_fallback_when_same_as_primary():
    backend = make_backend(_config(name="google", fallback="google"))
    assert isinstance(backend, GoogleBackend)


def test_make_backend_wires_gemini_config_fields(monkeypatch):
    genai = pytest.importorskip("google.genai")
    from tests.fixtures.fake_gemini_client import FakeGeminiClient

    monkeypatch.setattr(genai, "Client", lambda: FakeGeminiClient())
    cfg = Config(
        backend=BackendConfig(
            name="gemini", fallback=None,
            gemini=GeminiBackendConfig(model="gemini-3.6-flash", batch_size=7),
        )
    )
    backend = make_backend(cfg)
    assert backend.name == "gemini"
    assert backend.model == "gemini-3.6-flash"
    assert backend.max_batch == 7


def test_make_backend_wraps_fallback():
    # Same-name fallback collapses to no wrapper (tested above); use two
    # distinct names to confirm wrapping -- anthropic requires the
    # optional dependency, so exercise the wrapping logic directly instead
    # of via make_backend().
    fb = FallbackBackend(FakeBackend(), GoogleBackend())
    assert fb.name == "fake+fallback:google"


# -- FallbackBackend: protection-aware per-attempt calls ---------------------

def test_fallback_not_invoked_when_primary_succeeds():
    primary = FakeBackend(uses_placeholder_protection=False)
    fallback = FailingBackend()
    fb = FallbackBackend(primary, fallback)
    result = fb.translate("hola", CTX)
    assert result.status == "ok"


def test_fallback_invoked_when_primary_fails():
    primary = FailingBackend()
    fallback = FakeBackend(uses_placeholder_protection=False, translate_fn=lambda s: "rescued")
    fb = FallbackBackend(primary, fallback)
    result = fb.translate("hola", CTX)
    assert result.status == "ok"
    assert result.text == "rescued"


def test_fallback_protects_entities_when_its_own_flag_requires_it():
    """Primary doesn't want placeholder protection; fallback does. The
    fallback attempt must still get entity protection even though the
    top-level FallbackBackend.uses_placeholder_protection is False (it
    handles this per sub-backend, not by delegating to Translator)."""
    primary = FailingBackend()  # uses_placeholder_protection=True but always fails
    calls = []

    def _echo_placeholders(s):
        calls.append(s)
        return s  # echoes back whatever it received, placeholders included

    fallback = FakeBackend(uses_placeholder_protection=True, translate_fn=_echo_placeholders)
    fb = FallbackBackend(primary, fallback)
    result = fb.translate("Grupo Meridian pagó la deuda.", CTX)
    assert result.status == "ok"
    assert "[[0]]" in calls[0]  # fallback backend saw the protected form
    assert result.text == "Grupo Meridian pagó la deuda."  # restored after echo


def test_fallback_both_backends_fail():
    fb = FallbackBackend(FailingBackend(), FailingBackend())
    result = fb.translate("hola", CTX)
    assert result.status == "failed"


def test_fallback_declares_no_placeholder_protection_itself():
    fb = FallbackBackend(FakeBackend(), FakeBackend())
    assert fb.uses_placeholder_protection is False


def test_fallback_max_batch_is_minimum_of_both():
    primary = FakeBackend()
    primary.max_batch = 25
    fallback = GoogleBackend(max_batch=20)
    fb = FallbackBackend(primary, fallback)
    assert fb.max_batch == 20


# -- FallbackBackend.translate_batch ------------------------------------

def test_fallback_batch_falls_through_per_unit_on_failure():
    # FakeBackend.translate returns status="ok" always via its
    # translate_fn wrapper -- build a custom stand-in that fails for "bad".
    class _SelectivePrimary:
        name = "selective"
        prefers_batch = True
        max_batch = 10
        uses_placeholder_protection = False

        def translate(self, text, ctx):
            if text == "bad":
                return TranslationResult(text=None, status="failed")
            return TranslationResult(text=text.upper(), status="ok")

        def translate_batch(self, texts, ctx):
            return [self.translate(t, ctx) for t in texts]

        def estimate(self, texts, ctx):
            return None

    fallback = FakeBackend(uses_placeholder_protection=False, translate_fn=lambda s: "rescued")
    fb = FallbackBackend(_SelectivePrimary(), fallback)
    results = fb.translate_batch(["good", "bad"], CTX)
    assert results[0].status == "ok"
    assert results[0].text == "GOOD"
    assert results[1].status == "ok"
    assert results[1].text == "rescued"


def test_fallback_estimate_delegates_to_primary():
    from palimpsest.translate.backend import Cost

    class _Priced:
        name = "priced"
        prefers_batch = True
        max_batch = 10
        uses_placeholder_protection = False

        def translate(self, text, ctx):
            return TranslationResult(text=text, status="ok")

        def translate_batch(self, texts, ctx):
            return [self.translate(t, ctx) for t in texts]

        def estimate(self, texts, ctx):
            return Cost(input_tokens=1, output_tokens=1, usd=0.01)

    fb = FallbackBackend(_Priced(), FakeBackend())
    cost = fb.estimate(["a"], CTX)
    assert cost is not None
    assert cost.usd == 0.01


def test_fallback_exposes_primary_model():
    class _Modeled:
        name = "modeled"
        model = "claude-opus-5"
        prefers_batch = True
        max_batch = 10
        uses_placeholder_protection = False

        def translate(self, text, ctx):
            return TranslationResult(text=text, status="ok")

        def translate_batch(self, texts, ctx):
            return [self.translate(t, ctx) for t in texts]

        def estimate(self, texts, ctx):
            return None

    fb = FallbackBackend(_Modeled(), GoogleBackend())
    assert fb.model == "claude-opus-5"


# -- build_translator -----------------------------------------------------

def test_build_translator_writes_cache_under_configured_cache_dir(tmp_path):
    config = Config(paths=PathsConfig(cache_dir=tmp_path / "cache"))
    backend = FakeBackend(uses_placeholder_protection=False)
    tr = build_translator(
        "Corporate/Trust deed.pdf", config, backend,
        entities=(), glossary=Glossary(), post_rules=(),
    )
    assert isinstance(tr, Translator)
    assert tr.cache.path.parent == tmp_path / "cache"


def test_build_translator_namespace_changes_with_entities(tmp_path):
    config = Config(paths=PathsConfig(cache_dir=tmp_path / "cache"))
    backend = FakeBackend(uses_placeholder_protection=False)
    tr_a = build_translator(
        "doc.pdf", config, backend, entities=("Grupo Meridian",),
        glossary=Glossary(), post_rules=(),
    )
    tr_b = build_translator(
        "doc.pdf", config, backend, entities=("Grupo Aurora",),
        glossary=Glossary(), post_rules=(),
    )
    assert tr_a.cache.namespace != tr_b.cache.namespace


def test_build_translator_same_rel_path_same_cache_file_across_calls(tmp_path):
    config = Config(paths=PathsConfig(cache_dir=tmp_path / "cache"))
    backend = FakeBackend(uses_placeholder_protection=False)
    tr_a = build_translator(
        "doc.pdf", config, backend, entities=(), glossary=Glossary(), post_rules=()
    )
    tr_b = build_translator(
        "doc.pdf", config, backend, entities=(), glossary=Glossary(), post_rules=()
    )
    assert tr_a.cache.path == tr_b.cache.path
