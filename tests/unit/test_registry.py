import pytest

from palimpsest.config.model import (
    BackendConfig,
    Config,
    GeminiBackendConfig,
    GoogleBackendConfig,
    PathsConfig,
)
from palimpsest.core.errors import DependencyError
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import TranslationContext, TranslationResult
from palimpsest.translate.google import GoogleBackend
from palimpsest.translate.registry import (
    FallbackBackend,
    _has_credentials,
    build_translator,
    make_backend,
)
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


# -- _has_credentials ---------------------------------------------------

def test_has_credentials_google_is_always_true(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert _has_credentials("google") is True


def test_has_credentials_gemini_checks_either_env_var(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert _has_credentials("gemini") is False
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert _has_credentials("gemini") is True


def test_has_credentials_anthropic_checks_its_env_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _has_credentials("anthropic") is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert _has_credentials("anthropic") is True


# -- allow_env_fallback: the multi-tenant leak-prevention gate --------------
#
# The security property `server/routes.py::_resolve_key` and this module
# together must guarantee: a caller resolving keys for a non-local
# visitor with no key of their own (`anthropic_api_key=None`,
# `allow_env_fallback=False`) must NEVER end up constructing an SDK
# client that falls back to reading this process's own environment --
# even when that environment genuinely has a real key sitting in it
# (the operator's own key, in the hosted-deployment scenario this
# defends). See `translate.registry.make_backend`'s docstring.

def test_build_one_refuses_env_fallback_for_anthropic_even_when_env_has_a_key(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-the-operators-own-key")
    with pytest.raises(DependencyError):
        make_backend(_config(name="anthropic"), anthropic_api_key=None, allow_env_fallback=False)


def test_build_one_refuses_env_fallback_for_gemini_even_when_env_has_a_key(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setenv("GEMINI_API_KEY", "the-operators-own-key")
    with pytest.raises(DependencyError):
        make_backend(_config(name="gemini"), gemini_api_key=None, allow_env_fallback=False)


def test_build_one_uses_explicit_key_when_env_fallback_disallowed(monkeypatch):
    genai = pytest.importorskip("google.genai")
    from tests.fixtures.fake_gemini_client import FakeGeminiClient

    seen_kwargs = {}

    def _fake_client(**kwargs):
        seen_kwargs.update(kwargs)
        return FakeGeminiClient()

    monkeypatch.setattr(genai, "Client", _fake_client)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    backend = make_backend(
        _config(name="gemini"), gemini_api_key="visitor-own-key", allow_env_fallback=False
    )
    assert backend.name == "gemini"
    assert seen_kwargs.get("api_key") == "visitor-own-key"


def test_has_credentials_ignores_env_when_fallback_disallowed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-operators-own-key")
    assert _has_credentials("anthropic", allow_env_fallback=False) is False
    assert _has_credentials("anthropic", "a-visitor-key", allow_env_fallback=False) is True


def test_make_backend_never_wires_an_env_only_fallback_for_a_scoped_visitor(monkeypatch):
    """Primary is google (needs no key, always usable); an operator's own
    ANTHROPIC_API_KEY sits in the environment, exactly as it would on a
    hosted server. A visitor with no Anthropic key of their own must not
    get that fallback wired up on their behalf."""
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-the-operators-own-key")
    backend = make_backend(
        _config(name="google", fallback="anthropic"),
        anthropic_api_key=None, allow_env_fallback=False,
    )
    assert isinstance(backend, GoogleBackend)  # no FallbackBackend wrapper


# -- make_backend: fallback requires usable credentials ----------------------
#
# A credential-less fallback is worse than none: FallbackBackend retries
# via it on every non-ok primary result, including the primary's own
# legitimate per-unit failures, and a credential-less SDK client can
# raise in a way that crashes the whole document instead of leaving one
# unit honestly untranslated (see registry.make_backend's docstring).

def test_make_backend_skips_fallback_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = make_backend(_config(name="google", fallback="anthropic"))
    assert isinstance(backend, GoogleBackend)  # no FallbackBackend wrapper at all


def test_make_backend_wires_fallback_when_credentials_present(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    backend = make_backend(_config(name="google", fallback="anthropic"))
    assert isinstance(backend, FallbackBackend)
    assert backend.fallback.name == "anthropic"


def test_make_backend_wires_gemini_config_fields(monkeypatch):
    genai = pytest.importorskip("google.genai")
    from tests.fixtures.fake_gemini_client import FakeGeminiClient

    monkeypatch.setattr(genai, "Client", lambda **_kwargs: FakeGeminiClient())
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
