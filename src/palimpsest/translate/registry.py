"""Builds a `Backend` from `Config.backend`, wiring the configured
primary backend to an optional fallback.

Why the fallback isn't just "try backend A, then backend B" at the
`Translator` layer
--------------------------------------------------------------------------
The two backends disagree about *how* entity/number protection works
(`Backend.uses_placeholder_protection` -- see `translate.backend`'s module
docstring): Google needs the text placeholdered before the call, Claude
needs it raw. If a fallback simply forwarded whatever text the primary
backend was given, a Claude-primary/Google-fallback pair would hand
Google raw Spanish with no protection on a fallback attempt -- exactly
the class of bug (`GRUPO` -> `CLUSTER`) protection exists to prevent, for
every fallback translation. `FallbackBackend` applies each sub-backend's
OWN protection scheme on each attempt, and so declares
`uses_placeholder_protection = False` to its caller: it always receives
raw text and decides internally, per sub-backend, how to protect it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from palimpsest.config.model import Config
from palimpsest.core import paths as core_paths
from palimpsest.core.errors import ConfigError, DependencyError
from palimpsest.text.glossary import Glossary
from palimpsest.text.protect import all_tokens_restored, build_protect_re, protect, restore
from palimpsest.translate.backend import Backend, Cost, TranslationContext, TranslationResult
from palimpsest.translate.cache import compute_namespace
from palimpsest.translate.google import GoogleBackend
from palimpsest.translate.translator import Translator

_KNOWN = ("google", "anthropic", "gemini")


def _has_credentials(
    name: str,
    anthropic_api_key: str | None = None,
    gemini_api_key: str | None = None,
    *,
    allow_env_fallback: bool = True,
) -> bool:
    """Best-effort check of whether a key is available for `name` -- used
    only to decide whether it's worth wiring up as a FALLBACK (see
    `make_backend`), never to gate using it as the primary backend
    directly (each backend's own constructor is the source of truth
    there, and raises its own clear error if misconfigured).

    An explicit `anthropic_api_key`/`gemini_api_key` (a per-visitor key
    resolved by the server, see `server/routes.py::_resolve_key`) always
    wins. Failing that, `allow_env_fallback` (default `True`, matching
    the CLI's and the server's local/single-user behavior) checks the
    documented env var each backend's own SDK would otherwise resolve a
    key from -- deliberately only that var, not every auth method the
    SDK supports (e.g. anthropic's `auth_token` or an `ant auth login`
    profile), since getting this wrong in the "available" direction just
    means the fallback attempt fails as before this check existed.

    `allow_env_fallback=False` is what the server passes for any visitor
    other than the local one (`server/routes.py::_LOCAL_VISITOR`) -- an
    unrelated credential sitting in this process's own environment (the
    OPERATOR's key) must never get silently wired up as a fallback for
    a random public visitor who didn't supply their own."""
    if name == "google":
        return True  # deep_translator's free scrape, no key at all
    if name == "gemini":
        if gemini_api_key:
            return True
        return allow_env_fallback and bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
    if name == "anthropic":
        if anthropic_api_key:
            return True
        return allow_env_fallback and bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False


def _build_one(
    name: str,
    config: Config,
    *,
    anthropic_api_key: str | None = None,
    gemini_api_key: str | None = None,
    allow_env_fallback: bool = True,
) -> Backend:
    if name == "google":
        g = config.backend.google
        return GoogleBackend(max_batch=g.batch_size, retry_pause=g.pause_seconds)
    if name == "anthropic":
        from palimpsest.translate.anthropic import AnthropicBackend

        if anthropic_api_key is None and not allow_env_fallback:
            raise DependencyError("no Anthropic API key configured for this session")
        return AnthropicBackend.from_config(config.backend.anthropic, api_key=anthropic_api_key)
    if name == "gemini":
        from palimpsest.translate.gemini import GeminiBackend

        if gemini_api_key is None and not allow_env_fallback:
            raise DependencyError("no Gemini API key configured for this session")
        return GeminiBackend.from_config(config.backend.gemini, api_key=gemini_api_key)
    raise ConfigError(f"unknown backend {name!r} (expected one of {_KNOWN})")


def make_backend(
    config: Config,
    *,
    anthropic_api_key: str | None = None,
    gemini_api_key: str | None = None,
    allow_env_fallback: bool = True,
) -> Backend:
    """The backend named by `[backend].name`, wrapped with the one named
    by `[backend].fallback` if configured, different, and actually usable.

    A fallback with no credentials is worse than no fallback at all: the
    primary backend's OWN per-unit failures (e.g. a legitimate entity/
    number verification mismatch -- an expected, honest outcome, not a
    bug) would otherwise trigger a fallback attempt on every single one,
    and a credential-less SDK client raises on the first real call in a
    way this project's exception handling can't always turn into a clean
    per-unit failure (see `translate.anthropic`'s lazy credential
    resolution) -- crashing the whole job instead of leaving that one
    unit honestly untranslated and continuing, exactly what would have
    happened with no fallback configured.

    `anthropic_api_key`/`gemini_api_key`/`allow_env_fallback` exist for
    the server's per-visitor credential resolution (see
    `server/routes.py::_resolve_key`) -- the CLI's own call site never
    passes them, which reproduces today's behavior exactly (`None` +
    `allow_env_fallback=True` is indistinguishable from the SDKs' own
    default env resolution). See `_build_one`/`_has_credentials` for how
    `allow_env_fallback=False` prevents ever constructing an SDK client
    with a key silently pulled from this process's own environment on a
    visitor's behalf."""
    primary = _build_one(
        config.backend.name, config,
        anthropic_api_key=anthropic_api_key, gemini_api_key=gemini_api_key,
        allow_env_fallback=allow_env_fallback,
    )
    fallback_name = config.backend.fallback
    if not fallback_name or fallback_name == config.backend.name:
        return primary
    if not _has_credentials(
        fallback_name, anthropic_api_key, gemini_api_key, allow_env_fallback=allow_env_fallback
    ):
        return primary
    fallback = _build_one(
        fallback_name, config,
        anthropic_api_key=anthropic_api_key, gemini_api_key=gemini_api_key,
        allow_env_fallback=allow_env_fallback,
    )
    return FallbackBackend(primary, fallback)


def build_translator(
    rel: str,
    config: Config,
    backend: Backend,
    entities: Sequence[str],
    glossary: Glossary,
    post_rules: Sequence[tuple[str, str]],
) -> Translator:
    """One `Translator` per document, matching the pipeline's per-document
    cache file. `entities`/`glossary`/`post_rules` are what the resulting
    cache namespace is computed from -- change any of them and a
    document's cache moves to a fresh namespace rather than silently
    serving stale output (see `translate.cache.compute_namespace`)."""
    key = core_paths.cache_key(core_paths.norm_rel(rel))
    cache_path = config.paths.cache_dir / f"{key}.json"
    namespace = compute_namespace(
        backend.name,
        getattr(backend, "model", None),
        config.language.source,
        config.language.target,
        glossary_terms=glossary.terms,
        entities=entities,
        post_rules=post_rules,
    )
    return Translator(
        cache_path,
        backend,
        cache_namespace=namespace,
        entities=entities,
        glossary=glossary,
        post_rules=post_rules,
        source=config.language.source,
        target=config.language.target,
    )


class FallbackBackend:
    name_prefix = "fallback"
    uses_placeholder_protection = False

    def __init__(self, primary: Backend, fallback: Backend):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+fallback:{fallback.name}"
        self.model = getattr(primary, "model", None)
        self.prefers_batch = primary.prefers_batch
        self.max_batch = min(primary.max_batch, fallback.max_batch)

    def _call(self, backend: Backend, text: str, ctx: TranslationContext) -> TranslationResult:
        if not backend.uses_placeholder_protection:
            return backend.translate(text, ctx)
        protect_re = build_protect_re(ctx.entities)
        protected, tokens = protect(text, protect_re)
        result = backend.translate(protected, ctx)
        if result.status != "ok":
            return result
        restored = restore(result.text, tokens)
        if restored is None or not all_tokens_restored(restored):
            return TranslationResult(
                text=None, status="failed", detail="placeholder not restored"
            )
        return TranslationResult(text=restored, status="ok")

    def translate(self, text: str, ctx: TranslationContext) -> TranslationResult:
        result = self._call(self.primary, text, ctx)
        if result.status == "ok":
            return result
        return self._call(self.fallback, text, ctx)

    def translate_batch(
        self, texts: Sequence[str], ctx: TranslationContext
    ) -> list[TranslationResult]:
        """Batches through the primary only -- any non-"ok" result falls
        through to `translate()`, the same "leave it for the accurate
        single-string path" pattern `Translator.warm()` already uses for
        an imperfect batch result, so the correct per-unit fallback logic
        above lives in exactly one place."""
        if not self.primary.uses_placeholder_protection:
            primary_results = self.primary.translate_batch(list(texts), ctx)
        else:
            protect_re = build_protect_re(ctx.entities)
            pairs = [protect(t, protect_re) for t in texts]
            raw_results = self.primary.translate_batch([p[0] for p in pairs], ctx)
            primary_results = []
            for (_prot, tokens), result in zip(pairs, raw_results, strict=True):
                if result.status != "ok":
                    primary_results.append(result)
                    continue
                restored = restore(result.text, tokens)
                if restored is None or not all_tokens_restored(restored):
                    primary_results.append(
                        TranslationResult(
                            text=None, status="failed", detail="placeholder not restored"
                        )
                    )
                else:
                    primary_results.append(TranslationResult(text=restored, status="ok"))

        return [
            r if r.status == "ok" else self.translate(t, ctx)
            for t, r in zip(texts, primary_results, strict=True)
        ]

    def estimate(self, texts: Sequence[str], ctx: TranslationContext) -> Cost | None:
        return self.primary.estimate(texts, ctx)
