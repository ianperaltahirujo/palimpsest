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
  client-side; this is enforced server-side. `PrivateNetworkAccessMiddleware`
  (also `security.py`) answers the extra preflight check Chrome requires
  before a public HTTPS origin (like a GitHub Pages URL) may reach a
  loopback target like this server at all.
- API keys are read from the process environment exactly the way the
  CLI already does (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`), are never
  stored in a job record, and are never included in any response body
  -- `/api/health` reports only whether each is present. They CAN now
  be accepted over HTTP (`PUT /api/keys`, `routes.py`), which is a
  deliberate, narrow exception to "never over HTTP," made specifically
  so a key can be typed into a page instead of a shell: only from a
  request whose origin already passed `OriginCheckMiddleware` (so only
  an origin the caller explicitly allowlisted), only applied to this
  same loopback-bound process's own environment, and written only to
  a local `.env` this same machine controls -- never proxied, relayed,
  or logged. A `.env` file, if present, is also loaded into that same
  environment by `cli.py::main()` before `serve` even starts.

None of this is adequate for a hosted, multi-user deployment -- there is
still exactly one active key per running server process, no per-request
auth, and one shared job queue. It is adequate for what this is: a local
tool one person runs against their own documents on their own machine,
optionally driven from a frontend published somewhere else.
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
from palimpsest.server.security import OriginCheckMiddleware, PrivateNetworkAccessMiddleware
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
    backend_factory: Callable[[Config], Backend] = make_backend
    """Overridable so tests can inject a `FakeBackend` without a real
    network call or API key -- see `create_app`'s `backend_factory`
    parameter. Defaults to the real `translate.registry.make_backend`,
    exactly what the CLI uses."""
    _uploaded: dict[str, UploadedFile] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def remember_upload(self, uploaded: UploadedFile) -> None:
        with self._lock:
            self._uploaded[uploaded.file_id] = uploaded

    def get_upload(self, file_id: str) -> UploadedFile | None:
        with self._lock:
            return self._uploaded.get(file_id)

    def refresh_entities(self) -> None:
        self.entities = config_loader.load_entities(self.config)


def _load_state(
    config: Config, backend_factory: Callable[[Config], Backend]
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
    backend_factory: Callable[[Config], Backend] = make_backend,
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
        # CORSMiddleware answers the normal preflight (ACAO/ACAM/ACAH);
        # PrivateNetworkAccessMiddleware must be added AFTER it so it
        # wraps CORSMiddleware (Starlette's outermost layer = last
        # added) and can add the one extra header Chrome requires before
        # a public HTTPS origin may reach this loopback server at all --
        # see security.py.
        app.add_middleware(
            CORSMiddleware, allow_origins=list(extra_origins),
            allow_methods=["*"], allow_headers=["*"],
        )
        app.add_middleware(PrivateNetworkAccessMiddleware)

    app.include_router(router)

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="spa")

    return app
