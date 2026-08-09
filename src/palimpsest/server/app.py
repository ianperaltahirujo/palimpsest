"""The FastAPI application factory.

Local-first is the security model, not an absence of one
--------------------------------------------------------
This server has no accounts, no auth, and no concept of "which user" --
by design (see the plan this was built from: local-first single-user).
That is only safe because of what else is true:

- Binds to `127.0.0.1` unless the caller explicitly asks for something
  else (enforced in `cli.cmd_serve`, one layer up).
- No CORS is configured by default: the built SPA is served from this
  same FastAPI process, at the same origin, so the browser's own
  same-origin policy already does the job CORS headers exist to relax.
  `extra_origins` (from `--dev-origin`/`--dev`, or one or more
  `--allow-origin` flags -- e.g. a GitHub Pages URL hosting a
  standalone build of this same frontend) adds exactly those origins
  and nothing else. Every origin here must be one the caller
  explicitly names; this must never become a wildcard, since
  `OriginCheckMiddleware` (below) is what stands between an arbitrary
  webpage open in another tab and this server.
- `OriginCheckMiddleware` (see `security.py`) rejects any mutating
  cross-origin request regardless of CORS config, as a second,
  independent layer -- CORS is what a *compliant* browser enforces
  client-side; this is enforced server-side. `CORSMiddleware`'s
  `allow_private_network=True` (below, only set alongside a non-empty
  `extra_origins`) answers the extra preflight check Chrome requires
  before a public HTTPS origin (like a GitHub Pages URL) may reach a
  loopback target like this server at all.
- API keys are scoped per VISITOR (`routes.py::_visitor_id`/`_resolve_key`,
  `AppState._keys`), not read unconditionally from the process
  environment -- a request with no visitor id (curl, scripts, the
  classic single-user desktop workflow) falls back to one fixed local
  sentinel (`_LOCAL_VISITOR`), which alone still consults this process's
  own environment (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) and its local
  `.env`, exactly as before per-visitor scoping existed. Any OTHER
  visitor's key lives only in-memory in `AppState._keys`, is never
  stored in a job record, and is never included in any response body --
  `/api/health` reports only whether each is present, per visitor. Keys
  CAN be accepted over HTTP (`PUT /api/keys`, `routes.py`), a deliberate,
  narrow exception to "never over HTTP," made specifically so a key can
  be typed into a page instead of a shell -- reachable only from an
  origin `OriginCheckMiddleware` already allowed. Only the local
  sentinel's key is ever written to disk (a local `.env`, loaded back by
  `cli.py::main()` before `serve` even starts); every other visitor's
  key exists only for the lifetime of the server process and is lost on
  restart -- there is no persistence story for a hosted deployment's
  visitor keys, by design (see `translate.registry.make_backend`'s
  `allow_env_fallback` for the mechanism that keeps a non-local
  visitor's missing key from ever silently falling back to reading this
  process's own environment, which would leak the operator's own key).

This still isn't full multi-tenancy: there is no per-request auth (a
visitor id is self-reported, not verified), and one shared job queue
(`ThreadPoolExecutor(max_workers=1)`, `server/jobs.py`) serializes every
visitor's jobs regardless of whose key is attached to which. It is
adequate for what this is: a local tool one person runs against their
own documents, OR a publicly-hosted instance where per-visitor id scoping
keeps casual cross-visitor exposure from happening by accident during
normal use -- not a defense against a determined adversary reusing a
leaked id.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import find_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from palimpsest.config import loader as config_loader
from palimpsest.config.model import Config, DocumentMap
from palimpsest.server.jobs import JobRegistry
from palimpsest.server.security import OriginCheckMiddleware
from palimpsest.server.uploads import UploadedFile
from palimpsest.text import postfix
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import Backend
from palimpsest.translate.registry import make_backend


@dataclass
class AppState:
    config: Config
    entities: tuple[str, ...]
    glossary: Glossary
    documents: DocumentMap
    post_rules: tuple[tuple[str, str], ...]
    entities_path: Path
    uploads_dir: Path
    dotenv_path: Path
    """Where `PUT /api/keys` (`routes.py`) persists a submitted key --
    same resolution `cli.py::main()` uses to LOAD `.env`
    (`find_dotenv(usecwd=True)`), computed once here rather than
    per-request so repeated submissions in one run always target the
    same file. Falls back to `<cwd>/.env` if none exists yet."""
    jobs: JobRegistry
    backend_factory: Callable[..., Backend] = make_backend
    """Overridable so tests can inject a `FakeBackend` without a real
    network call or API key -- see `create_app`'s `backend_factory`
    parameter. Defaults to the real `translate.registry.make_backend`,
    exactly what the CLI uses. Called with `anthropic_api_key`/
    `gemini_api_key`/`allow_env_fallback` kwargs (see
    `routes.py::_resolve_key`) -- `Callable[..., Backend]` rather than a
    narrower signature since a test's fake factory only needs to accept
    (and typically ignores) whichever of those it's given."""
    _uploaded: dict[str, UploadedFile] = field(default_factory=dict)
    _keys: dict[str, dict[str, str]] = field(default_factory=dict)
    """visitor_id -> {"ANTHROPIC_API_KEY": ..., "GEMINI_API_KEY": ...}.
    See `routes.py::_resolve_key`/`_LOCAL_VISITOR` for how this is read
    and when it falls back to this process's own environment."""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def remember_upload(self, uploaded: UploadedFile) -> None:
        with self._lock:
            self._uploaded[uploaded.file_id] = uploaded

    def get_upload(self, file_id: str, visitor_id: str) -> UploadedFile | None:
        """`None` both when `file_id` is unknown AND when it belongs to a
        DIFFERENT visitor -- callers must not distinguish the two (see
        `routes.py`'s 404-not-403 reasoning), which is exactly why this
        one check lives here rather than at each call site."""
        with self._lock:
            uploaded = self._uploaded.get(file_id)
        if uploaded is None or uploaded.visitor_id != visitor_id:
            return None
        return uploaded

    def get_keys(self, visitor_id: str) -> dict[str, str]:
        with self._lock:
            return dict(self._keys.get(visitor_id, {}))

    def set_key(self, visitor_id: str, env_name: str, value: str) -> None:
        with self._lock:
            self._keys.setdefault(visitor_id, {})[env_name] = value

    def refresh_entities(self) -> None:
        self.entities = config_loader.load_entities(self.config)


def _load_state(
    config: Config, backend_factory: Callable[..., Backend]
) -> AppState:
    config.paths.ensure_dirs()

    # If no private entities file is configured, pin one down under
    # work_dir and fold it into `config.private.entities` right here --
    # every subsequent read (`get_entities`, `refresh_entities`) goes
    # through `config_loader.load_entity_groups(state.config)`, which
    # only ever looks at `config.private.entities`. Without this, a PUT
    # would write to the fallback path while GET kept reading from a
    # `None` path and finding nothing -- a real bug caught by
    # `test_entities_round_trip` in test_server_api.py, not a
    # hypothetical one.
    if config.private.entities is None:
        entities_path = config.paths.work_dir / "entities.toml"
        config = dataclasses.replace(
            config, private=dataclasses.replace(config.private, entities=entities_path)
        )
    else:
        entities_path = config.private.entities

    entities = config_loader.load_entities(config)
    glossary = (
        Glossary.load(domains=config.glossary.domains, extra=config.glossary.extra)
        if config.glossary.domains or config.glossary.extra
        else Glossary()
    )
    documents = config_loader.load_documents(config)
    post_rules = tuple(postfix.load(sets=config.postrules.sets, extra=config.postrules.extra))

    uploads_dir = config.paths.work_dir / "server" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = config.paths.work_dir / "server" / "jobs"
    dotenv_path = Path(find_dotenv(usecwd=True) or (Path.cwd() / ".env"))

    return AppState(
        config=config, entities=entities, glossary=glossary, documents=documents,
        post_rules=post_rules, entities_path=entities_path, uploads_dir=uploads_dir,
        dotenv_path=dotenv_path, jobs=JobRegistry(jobs_dir), backend_factory=backend_factory,
    )


def create_app(
    config: Config,
    *,
    static_dir: Path | None = None,
    extra_origins: frozenset[str] = frozenset(),
    backend_factory: Callable[..., Backend] = make_backend,
) -> FastAPI:
    """`static_dir`, if given, is the built SPA (`web/prototype/dist`),
    mounted at `/` so the app is served from the same origin as the API
    -- see the module docstring for why that matters. `extra_origins`
    (e.g. `{"http://localhost:5173"}` for `--dev`, or a GitHub Pages URL
    from one or more `--allow-origin` flags) are the ONLY origins
    allowed cross-origin; empty in a plain production `palimpsest serve`.
    `backend_factory` exists so tests can inject a `FakeBackend` --
    production callers never pass it."""
    from palimpsest.server.routes import router

    app = FastAPI(title="palimpsest", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.palimpsest = _load_state(config, backend_factory)

    app.add_middleware(OriginCheckMiddleware, allowed_origins=extra_origins)
    if extra_origins:
        # allow_private_network=True answers the extra CORS-preflight
        # check Chrome requires before a public HTTPS origin may reach a
        # loopback target (this server) at all. Without it, Starlette's
        # own CORSMiddleware treats a preflight that carries
        # Access-Control-Request-Private-Network as a FAILURE and
        # returns 400 "Disallowed CORS private-network" -- verified by a
        # real curl preflight against a running server, not just
        # inspecting this call. (An earlier version of this code hand-
        # rolled a middleware to bolt the response header on afterward;
        # that left the 400 status untouched, which a real browser would
        # treat as a rejected preflight regardless of headers present --
        # don't reintroduce that. Starlette added native support for
        # this; check `allow_private_network` is still accepted by
        # `starlette.middleware.cors.CORSMiddleware` before removing
        # this parameter in a future refactor.)
        app.add_middleware(
            CORSMiddleware, allow_origins=list(extra_origins),
            allow_methods=["*"], allow_headers=["*"], allow_private_network=True,
        )

    app.include_router(router)

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="spa")

    return app
