# Production image for `palimpsest serve --api-only` (see docs/deployment.md
# for the full Render walkthrough). Single-stage, no frontend build -- the
# web UI is published separately (e.g. GitHub Pages) and points its "Server
# address" setting at wherever this container ends up hosted.
#
# No LibreOffice: Office-file page PREVIEW (Compare view) already degrades
# to a clean 503 without it (office/render.py's DependencyError path, no
# code change needed). OCR has no equivalent fallback -- tesseract,
# ghostscript, and qpdf are real requirements for any scanned PDF, not
# optional -- so only those are installed. Skipping LibreOffice keeps this
# image meaningfully smaller, which matters on a free-tier host.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    ghostscript \
    qpdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copied before the rest of the source so `pip install` only reruns when
# dependencies actually change, not on every source edit.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[server,ocr,anthropic,gemini]"

# Auto-discovered from the working directory by cli.py's own config
# resolution (config_path=None -> ./palimpsest.toml if present) -- no
# --config flag needed at runtime. See the file itself for what it
# overrides and why.
COPY docker/palimpsest.toml ./palimpsest.toml

# Documents intent -- Render (and most PaaS hosts) inject the real port to
# bind via $PORT at runtime regardless of this declaration.
EXPOSE 8765

# --host 0.0.0.0: this process must accept connections from outside the
# container; --i-know confirms that deliberately (the container boundary,
# not this bind address, is what actually limits reachability here).
# --api-only: no static SPA mount -- the frontend is published separately.
# --allow-origin: the ONE origin allowed to make cross-origin requests --
# update this if you publish the frontend somewhere else (see
# docs/deployment.md). --no-browser: no browser exists in this container
# to open. Shell form so ${PORT:-8765} actually expands.
CMD ["sh", "-c", "palimpsest serve --host 0.0.0.0 --i-know --port ${PORT:-8765} --api-only --allow-origin https://ianperaltahirujo.github.io --no-browser"]
