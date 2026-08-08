"""Page-raster preview for Office files, via LibreOffice headless.

Why not PyMuPDF's built-in Office "support"
---------------------------------------------
`fitz.open()` accepts .docx/.pptx/.xlsx without erroring, which looks
like native page rendering -- it isn't. Verified empirically against
both hand-built minimal OOXML packages and real `python-docx`/
`python-pptx` output: a 3-page .docx (explicit page breaks) and a
3-slide .pptx each report exactly ONE page, a fixed 400x600pt canvas
unrelated to the real page/slide size, with every page's or slide's
text concatenated onto it. It's a plain-text-reflow fallback, not a
layout renderer, and a spreadsheet's cells don't extract as text at
all. Showing that as a "page preview" would misrepresent the document
-- worse than an honest "not available" gap.

What this does instead
-----------------------
Shells out to LibreOffice headless (`soffice --headless --convert-to
pdf`) to get a REAL rendering, then hands the result to the existing
`qa.compare.render_page` PDF pipeline for actual page images. Same
pattern as `pdf.ocr`'s Tesseract dependency: an optional external
program, checked explicitly, with an actionable `DependencyError`
rather than a confusing subprocess failure if it's missing -- nothing
about translation itself depends on this, only the Compare preview
does. Conversion is slow (LibreOffice's own startup cost, commonly a
few seconds), so callers should do it lazily and cache the result --
see `server.routes.page_png`, which converts on first request per file
rather than eagerly at upload or job-completion time.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from palimpsest.core.errors import DependencyError

CONVERTIBLE_OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".xls"}

# Checked only when `soffice`/`soffice.exe` isn't already on PATH --
# LibreOffice's own installer does not reliably add itself to PATH on
# Windows, so a plain `shutil.which` alone misses a perfectly real
# local install (this list is exactly that gap, not a substitute for
# PATH).
_COMMON_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/opt/libreoffice/program/soffice",
)


def find_soffice() -> str | None:
    for name in ("soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _COMMON_SOFFICE_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _check_installed() -> str:
    soffice = find_soffice()
    if soffice is None:
        raise DependencyError(
            "LibreOffice is required to preview Office files -- install it (soffice must "
            "be on PATH or in a default install location); see "
            "https://www.libreoffice.org/download/download/. Translation itself does not "
            "need this -- only the page preview does."
        )
    return soffice


def ensure_preview_pdf(src: Path, out_dir: Path, key: str) -> Path:
    """Convert `src` to `out_dir/{key}.preview.pdf` via LibreOffice
    headless and return that path. Reuses an existing conversion if
    it's already newer than `src` -- same mtime-cache pattern as
    `pdf.ocr.ensure_ocr`, so repeated page requests for the same file
    don't re-run LibreOffice."""
    if src.suffix.lower() not in CONVERTIBLE_OFFICE_EXTENSIONS:
        raise DependencyError(f"cannot preview {src.suffix} files")
    soffice = _check_installed()

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{key}.preview.pdf"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out

    # LibreOffice names its output after the source file's stem and
    # writes wherever --outdir points, not to a name we control --
    # convert into a private scratch dir so concurrent conversions can
    # never collide on that generated filename, then move the one file
    # we actually asked for to the stable `key`-named path callers use.
    scratch = out_dir / f".preview-{key}"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [
                soffice, "--headless", "--norestore",
                "--convert-to", "pdf", "--outdir", str(scratch), str(src),
            ],
            capture_output=True, text=True, timeout=120,
        )
        produced = scratch / f"{src.stem}.pdf"
        if res.returncode != 0 or not produced.is_file():
            raise DependencyError(
                f"LibreOffice could not convert {src.name} for preview (exited "
                f"{res.returncode}). Its own error:\n{res.stderr[-800:]}"
            )
        produced.replace(out)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return out
