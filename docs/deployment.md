# Hosting the backend for a public, zero-command frontend

The GitHub Pages build of `web/prototype` is a static site with no API of its own -- by default,
every visitor is expected to point it at a `palimpsest serve` running on their own machine (see
`SECURITY.md`). This doc covers the other option: running one backend somewhere persistent, so a
visitor can open the page, type an API key, and translate a document without ever running a
command. See `src/palimpsest/server/app.py`'s module docstring for exactly what security
properties this backend still has (and doesn't) once it's reachable by more than one visitor --
read that before hosting one publicly.

**This doc is a walkthrough, not something this assistant can do for you.** Creating a Render
account, connecting a repository, and attaching any billing are all your own actions -- nothing
here creates external accounts or spends money on your behalf.

## What's already built for this

- `Dockerfile` (repo root): a single-stage image running `palimpsest serve --api-only`. No
  frontend build inside it -- the frontend is GitHub Pages, a separate deployment. No LibreOffice
  (Office file *preview* degrades to a clean 503 without it; OCR has no such fallback, so
  `tesseract-ocr`/`ghostscript`/`qpdf` are installed and LibreOffice deliberately isn't, to keep
  the image smaller).
- `docker/palimpsest.toml`: the one config file baked into the image. Overrides `[limits]`
  (a smaller `max_upload_bytes` than the local default) and `[ocr].jobs` (caps ocrmypdf's own
  concurrent-worker default -- see "OCR memory" below) -- every other setting is a packaged
  default, and paths are left alone entirely (the image's `WORKDIR` is `/app`, so the default
  relative paths like `.palimpsest/work` already resolve correctly inside the container).
- `--api-only` (new CLI flag, alongside the existing `--dev`): skips the static SPA mount without
  assuming a local Vite dev server the way `--dev` does.
- `GET /api/health` doubles as the platform health check -- no new code needed.
- A `docker` job in `.github/workflows/ci.yml` builds this image and smoke-tests `/api/health` on
  every push -- if that job is green, the image at least starts and answers.

## The tradeoff you're accepting: no persistent disk

Render's free web-service tier has **no persistent volume**. The container's filesystem is
whatever the image shipped with, plus anything written at runtime -- and all of that disappears
on redeploy, and the instance **sleeps after roughly 15 minutes idle**, so the first request after
a quiet period pays a real cold-start cost (the container has to boot from scratch). Concretely:

- Every visitor's uploaded documents, translation cache, and any key they typed into the page are
  gone the moment the instance restarts or redeploys. There is no warning for this beyond what's
  written here -- a visitor mid-translation across a redeploy loses their in-flight job.
- This is an accepted, deliberate tradeoff for a $0 budget, not something this setup tries to
  paper over. If that's not acceptable, the fix is a paid tier with a persistent disk (Render or
  otherwise) and pointing `[paths]` at it in `docker/palimpsest.toml` -- out of scope here.

## OCR memory (learned from a real incident)

Translating a real 3-page scanned PDF on this exact hosting setup OOM-killed the Render
instance -- confirmed via Render's own dashboard event log: *"Ran out of memory (used over
512MB) while running your code."* The job vanished without a trace (a plain `404 unknown job`
on the next check, not a `"failed"` status) because the replacement container's filesystem is
completely empty -- see "The tradeoff you're accepting" above; this is that tradeoff showing up
for real, not a separate bug.

Root cause: `ocrmypdf` (invoked by `pdf/ocr.py::ensure_ocr()`) defaults to one worker process
**per CPU core the host reports** -- not a container's actual memory allocation -- and each
concurrent worker holds a full page raster buffer. Render's shared infrastructure can report
more cores than a free-tier instance's real 512MB can back. `docker/palimpsest.toml` now sets
`[ocr] jobs = 1` to cap this (see `docs/configuration.md`'s OCR section and
`config.model.OcrConfig.jobs`'s docstring for the full reasoning) -- confirmed via a real
before/after test against this exact deployment with the same document that originally failed.

This substantially reduces the risk for typical few-page documents but does **not** eliminate it
for arbitrarily large or complex scans on a 512MB tier -- Ghostscript/Tesseract memory still
scales with page complexity even at `jobs=1`. If a large scan still OOMs, the honest fixes are a
paid tier with more memory, or a scan-specific page/size cap tighter than `[limits]` already
provides -- neither is built here yet.

Separately, the frontend (`Running.jsx`) now detects a job that's genuinely vanished or gone
silent -- instead of freezing forever on "OCR: waiting," it periodically checks the job's real
server-side status and, if it's gone, says so plainly and returns to a clean state instead of a
silent hang. That doesn't recover the lost work (nothing can, on this hosting tier), but it stops
the UI from lying about what happened.

## Render setup (your own steps)

1. **Create a Render account** (render.com) if you don't have one, and connect it to the GitHub
   account/org this repo lives under.
2. **New Web Service** → pick this repository. Render will detect the root `Dockerfile`
   automatically ("Docker" as the environment/runtime); no build command or start command needs
   to be typed in -- both come from the `Dockerfile` itself.
3. **Instance type**: the free tier. No payment method is required for Render's free web services
   (verify this is still true for your account/region before proceeding -- pricing pages change).
4. **Environment variables**: none are required to boot -- keys are supplied per-visitor at
   runtime via the web UI's key box (`PUT /api/keys`), not baked into the image or set here. If
   you want a fallback key for yourself as the "local" visitor (i.e. requests with no
   `X-Palimpsest-Visitor` header, which normally only happens via `curl`/scripts against this
   deployment, not the web UI), you could set `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` here -- most
   deployments won't need to.
5. **Deploy.** Render builds the image and gives you a URL like `https://<service-name>.onrender.com`.
6. **Confirm the origin the `Dockerfile` allows matches your actual GitHub Pages URL.** The
   `CMD` line hardcodes `--allow-origin https://ianperaltahirujo.github.io` -- an `Origin` header
   only ever carries scheme+host+port (never a path), so this is correct regardless of which
   repo/path the Pages site is served under, as long as it's published under that same GitHub
   account. If you fork this project and publish your OWN GitHub Pages build under a different
   account, edit that line before deploying, or your frontend's requests will be rejected by
   `OriginCheckMiddleware` (see `src/palimpsest/server/app.py`) -- verify with a real deploy, not
   just by reading this.
7. **Point the frontend at it.** Open the published GitHub Pages site → the "Server address"
   field (`web/prototype/src/config.js`'s `getApiBase()`/`setApiBase()`, a `localStorage` setting,
   not a build-time constant, since one public frontend build is shared by every visitor's own
   choice of backend) → enter `https://<service-name>.onrender.com`. This is per-browser, so each
   visitor who wants to use YOUR hosted backend rather than running their own sets this once.

## Verifying it actually works before telling anyone the link

1. `docker build -t palimpsest-server .` and `docker run -p 8765:8765 palimpsest-server` locally
   first -- confirm `curl http://localhost:8765/api/health` responds, then a real upload and
   translation through the web UI (pointed at `http://localhost:8765` via "Server address") before
   ever pushing to Render. (CI's `docker` job does the same build-and-health-check on every push,
   but a real translation needs a real API key, which CI never has.)
2. After deploying to Render: open the GitHub Pages site in two different browsers (or a normal
   window + an incognito window -- each gets its own `localStorage`, and so its own
   `pp-visitor-id`, simulating two different visitors), set a DIFFERENT API key in each, and
   confirm neither can see the other's key, uploads, or jobs. This is the whole point of the
   visitor-scoping work this backend now has (see `app.py`'s module docstring) -- verify it for
   real against the actual hosted instance, not just in the test suite.
3. Confirm the cold-start behavior is acceptable: let the instance sit idle 20+ minutes, then hit
   the site and time how long the first request takes. If that's too slow for your use case,
   that's the free tier's tradeoff showing up, not a bug to fix here.
