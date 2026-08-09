# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Python library / server

```bash
pip install -e ".[all,dev]"      # editable install, every backend + dev tools
pytest                            # full suite (ocr/network-marked tests excluded by default, see below)
pytest tests/unit/test_pdf_pipeline.py                          # one file
pytest tests/unit/test_pdf_pipeline.py::test_name_here          # one test
ruff check .                      # lint (line-length 100, see pyproject.toml for enabled rules)
mypy                               # type-check; file list is explicit in [tool.mypy].files, not the whole tree
python tools/scrub_check.py --history   # required before any PR touching docs/ or examples/ (also runs in CI)
```

Tests marked `@pytest.mark.ocr` (needs a real Tesseract install) or `@pytest.mark.network` (real network call) are
deselected by default (`pyproject.toml`'s `addopts`). No test may make a real network call — this is enforced by
convention, not just the marker.

### Web UI (`web/prototype/`)

```bash
cd web/prototype
npm install
npm run dev        # Vite dev server, http://localhost:5173, talks to the real API by default (see Two Modes below)
npm run build       # -> dist/
npm test            # vitest
npm run lint         # eslint
```

To serve the built SPA from the same origin as the API (production mode): `python tools/build_frontend.py` from
the repo root, then `palimpsest serve`. `--dev` binds only the API (no static mount) for use with `npm run dev`
against a live backend.

## Architecture

### Three layers, not one

1. **The library** (`src/palimpsest/`) — a standalone Python package usable via the `palimpsest` CLI with zero
   server/web dependencies.
2. **The server** (`src/palimpsest/server/`, optional `[server]` extra) — a FastAPI wrapper around the library,
   nothing more. It has no translation logic of its own; every route composes existing library functions.
3. **The web UI** (`web/prototype/`) — a React SPA. It has a MOCK mode (`VITE_MOCK=1`, fixtures from `state.jsx`,
   zero network calls, used for design review) and a REAL mode (default) that talks to the server. Every screen
   component branches on `MOCK` from `config.js` before touching `api.js` — check both branches when editing a
   screen, since they diverge more than they look.

### The translation pipeline (PDF path)

`pdf/pipeline.py::process_document` runs six phases in a fixed order — classify → OCR (scans only) → extract →
translate → clear → render/save — and this order is load-bearing: `text.protect.EntityGuard.skip()` must be
consulted before ANY text reaches a translation backend, and three historical bugs (documented in
`docs/design/protected-entities.md`) came from a call site that transformed text (label-splitting, prefix-peeling,
batch warm-up) and forgot to re-check the guard afterward. Every call path in `translate/translator.py` now funnels
through one `EntityGuard` instance — do not add a new backend-facing call site without routing through it.

**A paragraph that fails to translate is left untouched in the source language and listed in the report** — never
silently rendered as if translated, and never silently dropped. The translation cache (`translate/cache.py`) carries
an explicit status per entry (`ok`/`failed`/`identical`/`refused`); a failed entry is never served as if it were ok.

**`pdf.layout.extract_paragraphs`'s `min_size` threshold is a real footgun.** `config.thresholds.min_text_size_scan`
(default 7.0pt) silently drops any OCR'd text below that size, with no warning — a scan whose `ocrmypdf` output
happens to size its invisible text layer smaller than the default (this varies by source scan resolution and is not
predictable) will report a plausible-looking `translated: N` while having actually translated almost nothing,
because `extract_paragraphs` never handed most of the page to the translator at all. If a translated document comes
back mostly untouched, check the `Extract` phase's paragraph count against what the page visually contains before
suspecting the translation backend. Override per-project via `[thresholds]` in `palimpsest.toml` — see
`docs/design/bold-calibration.md` for the same "corpus-fitted, not universal" reasoning applied to a sibling
threshold.

### Office files are a second, unrelated pipeline

`.docx`/`.pptx`/`.xlsx` do NOT go through `pdf/pipeline.py`. `office/pipeline.py::translate_office_document` edits
the OOXML zip in place (`office/ooxml.py`), rewriting only text nodes. Its report shape has nothing in common with
the PDF report — `{"stats": {"nodes", "parts", "copied", "sheets_renamed"}, "diff", "failures": [str, ...]}` vs the
PDF report's `{"pages", "paragraphs", "translated", "skipped", "failed": [{"page","text","status"}, ...]}`. Anything
that consumes a job report (the web UI's Results screen, any new report-summarizing code) has to branch on which
shape it got — there is no shared report interface. `failures` here is a flat list of source strings with no page
number and no distinction between failed/refused/identical (that granularity is dropped, not preserved).

Office file preview (Compare view) is a THIRD, independent thing: `office/render.py` shells out to LibreOffice
headless (`soffice --headless --convert-to pdf`) to get a real page raster, converted lazily and cached on first
`GET /pages/{n}.png` request. This exists because `fitz.open()` silently "succeeds" on Office files without
actually rendering them (verified empirically — see the module's own docstring). Edit mode has no Office
equivalent at all (`pdf.layout`'s paragraph-rect model doesn't apply to a word processor or slide deck) —
`GET`/`PATCH /api/jobs/{id}/layout` reject Office files with a 400, and the web UI hides the Edit toggle for them.

### The IR serialization boundary (`core/ir.py`)

`pdf.layout.extract_paragraphs` and `pdf.render.draw_paragraph` both operate on live PyMuPDF objects; `core/ir.py`
is a plain-data snapshot of an extracted page (`Document`/`Page`/`Paragraph`/`Run`), convertible to/from JSON
without touching PyMuPDF. This is what makes the web UI's edit mode possible at all: `GET /api/jobs/{id}/layout`
serializes a real page through the IR, the browser edits it, and `PATCH /api/jobs/{id}/layout` → `pdf/reflow.py`
clears and redraws the whole page from a FRESH `extract_paragraphs` pass plus the edited paragraph list — not from
the client's stale rects — which is what makes calling PATCH twice on the same page safe. `pdf/render.py`'s
internal style tuple is `(font, size, bold, italic, color, underline, highlight)`; source-PDF extraction always
emits `False`/`None` for the last two — only edit-mode-driven reflow ever sets them.

### The server's security model is architectural, not bolted on

No auth, by design — see `server/app.py`'s module docstring. What actually stands in for it:
loopback-only binding by default (`--host` requires `--i-know`), and `server/security.py`'s `OriginCheckMiddleware`,
which checks a mutating request's `Origin` header against the request's OWN scheme+host+port (derived from the
`Host` header) rather than a static allowlist — same-origin is always allowed. Anything else — `--dev`'s Vite
origin, or one or more `--allow-origin` flags for a publicly-hosted frontend build (see below) — must be
explicitly named via `create_app`'s `extra_origins`; this must never become a wildcard, since this middleware is
what stands between an arbitrary webpage open in another tab and this server. (An earlier version only
allowlisted `--dev`'s origin and rejected every same-origin fetch/XHR from the production-built SPA itself, which
does send an `Origin` header even for same-origin requests — browsers do not let a page suppress it. Don't
reintroduce a static-allowlist-only check.)

**A standalone frontend build can be published somewhere other than this same server** — e.g. a GitHub Pages
build of `web/prototype`, with `web/prototype/src/config.js`'s `getApiBase()`/`setApiBase()` (a `localStorage`
setting, not a build-time constant, since one public build is shared by every user's own local server) pointed
back at `http://127.0.0.1:<port>`. That's a genuinely cross-origin browser tab reaching a loopback server, which
needs two things beyond `OriginCheckMiddleware`'s existing allowlist: `--allow-origin <exact origin>` on
`palimpsest serve` (never guessed or wildcarded — the caller must know and pass the real origin), and
`CORSMiddleware`'s `allow_private_network=True` (Starlette's own native support, passed in `app.create_app`
whenever `extra_origins` is non-empty), which answers the extra CORS-preflight check Chrome requires before a
public HTTPS origin may reach a private-network/loopback target at all. Without it, Starlette's `CORSMiddleware`
treats that preflight as a FAILURE and returns 400 even with everything else configured correctly — verified with
a real curl preflight against a running server, not just by reading the parameter's docs. (An earlier version of
this hand-rolled a middleware to bolt the response header on after the fact, which left the 400 status untouched
— a real browser evaluating a preflight looks at the status code, not just header presence. Don't reintroduce
that; use `allow_private_network=True` on `CORSMiddleware` itself.)

API keys are scoped per VISITOR, not read unconditionally from the server process's own environment.
`web/prototype/src/visitor.js` mints a random id per browser, sent as `X-Palimpsest-Visitor` (or a `visitor` query
param for the handful of requests — SSE, `<img>`/`<a>` URLs — that can't set custom headers); `routes.py`'s
`_visitor_id()` falls back to one fixed `_LOCAL_VISITOR` sentinel when neither is present (curl, scripts, the
classic single-user desktop workflow), which is exactly today's implicit single-scope behavior made explicit. This
is identity, not auth — nothing is signed, nothing stops a client from sending a different id on purpose; it only
keeps one visitor's browser from accidentally seeing another's keys/uploads/jobs during normal use, not a defense
against a determined adversary reusing a leaked id.

Each visitor's key lives in `AppState._keys` (in-memory, per-process, never persisted) and is never stored in a job
record or included in any response body — `GET /api/health` reports only whether each is present, for the
requesting visitor. `PUT /api/keys` (`routes.py::put_keys`) accepts a key over HTTP — a deliberate, narrow exception
to "keys never travel over HTTP," made specifically so a key can be typed into a page instead of a shell, reachable
only from an origin `OriginCheckMiddleware` already allowed. Only `_LOCAL_VISITOR`'s key ALSO goes to
`os.environ` and a local `.env` (via `python-dotenv`'s `set_key()`), so it survives a restart exactly as before
per-visitor scoping existed; `cli.py::main()` still loads that same `.env` before dispatching to any subcommand.
Every other visitor's key is lost on process restart — there is no persistence story for a hosted deployment's
visitor keys, by design (see `translate.registry.make_backend`'s `allow_env_fallback` for the deployment note
below).

**The critical correctness property**: `translate/registry.py::make_backend`/`_build_one`/`_has_credentials` accept
explicit `anthropic_api_key`/`gemini_api_key`/`allow_env_fallback` params. `anthropic.Anthropic(api_key=None)` and
`genai.Client(api_key=None)` do NOT mean "no key" to those SDKs — they mean "fall back to `os.environ` yourself,"
which would hand an unconfigured public visitor whatever key `_LOCAL_VISITOR` (the operator) has set. `routes.py`
resolves each visitor's key via `_resolve_key()` (per-visitor store first; environment fallback ONLY for
`_LOCAL_VISITOR`) and passes `allow_env_fallback=False` for every other visitor — `_build_one` then raises a clean
`DependencyError` (→ HTTP 503) directly, rather than ever constructing an SDK client with a key that could silently
resolve from this process's own environment. This closes the leak for both the PRIMARY backend and any configured
FALLBACK backend (`_has_credentials` no longer reads `os.environ` on a non-local visitor's behalf either — an
unrelated credential sitting in the operator's own environment must never get wired up as a fallback for a visitor
who didn't supply one).

None of this adds full multi-tenancy on its own: there is still no per-request auth (a visitor id is self-reported),
and one shared job queue (`ThreadPoolExecutor(max_workers=1)`, below) serializes every visitor's jobs regardless of
whose key is attached to which — a standalone frontend build widens WHERE the browser can be and WHOSE key gets
used, not a guarantee against a determined adversary. Per-visitor KEY scoping alone does not stop one visitor from
reading another's uploaded documents or translation results by guessing a job/file id — that's a separate
ownership check on top of the same visitor id, layered onto every job-scoped route.

Jobs run on one `ThreadPoolExecutor(max_workers=1)` per server process (`server/jobs.py`) — deliberate, not a
missing optimization; a local single-user tool has no reason to translate concurrently. `JobRegistry` persists each
job's state to disk on every change and reloads it on startup; a job still `queued`/`running` when the process
exited is marked `failed` on reload since there is no in-flight-resume story.

### Config layering

`config/loader.py::load()` merges packaged defaults → an optional project `palimpsest.toml` (auto-discovered from
CWD by the CLI/server if not passed explicitly) → `private/` (gitignored, per-user entity lists and document maps).
A missing `palimpsest.toml` is not an error — `palimpsest translate` works with zero config. See
`docs/configuration.md` for the full field reference and `examples/palimpsest.toml` for a fully-annotated example.
