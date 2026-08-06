"""OCR a scanned PDF to give it a text layer, via the `ocrmypdf` CLI.

Why this shells out to `python -m ocrmypdf` rather than importing it
----------------------------------------------------------------------
`ocrmypdf` is a full document pipeline (it drives Ghostscript, qpdf, and
Tesseract as external processes of its own); its supported integration
surface is its CLI, and running it out-of-process also means a crash in
that pipeline can never take this process down with it.

That invocation style is invisible to Python's own dependency tooling,
though -- no import scanner or `pip check` notices `ocrmypdf` missing.
Declared under the `[ocr]` extra (`palimpsest[ocr]`) so `pip install`
documents the dependency, and `ensure_ocr()` checks for it explicitly
before shelling out so the failure is an actionable `DependencyError`
instead of an opaque subprocess stderr dump.

`--skip-text`, never `--force-ocr`: these source PDFs typically have no
text layer at all, so `--skip-text` still OCRs every page -- but
`--force-ocr` rasterises each page and rebuilds the PDF from that raster,
which can multiply file size on an already-clean scan and needlessly
re-encodes the original image. `--skip-text` leaves the source image
bit-for-bit intact and only adds the invisible text layer.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from palimpsest.config.model import OcrConfig
from palimpsest.core.errors import ConfigError, DependencyError

_MODE_FLAGS = {"skip-text": "--skip-text", "force-ocr": "--force-ocr"}


def _check_installed() -> None:
    if importlib.util.find_spec("ocrmypdf") is None:
        raise DependencyError(
            "ocrmypdf is required to OCR scanned PDFs -- install with "
            "`pip install palimpsest-translate[ocr]` (Tesseract itself must also be "
            "installed and on PATH; see https://tesseract-ocr.github.io/tessdoc/Installation.html)"
        )


def ensure_ocr(src: Path, out_dir: Path, key: str, config: OcrConfig) -> Path:
    """OCR `src` to `out_dir/{key}_ocr.pdf` and return that path. Reuses
    the existing output if it's already newer than `src`, so a resumed
    batch run doesn't re-OCR every scan."""
    _check_installed()
    if config.mode not in _MODE_FLAGS:
        raise ConfigError(
            f"unknown [ocr].mode {config.mode!r} (expected one of {tuple(_MODE_FLAGS)})"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{key}_ocr.pdf"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out

    env = dict(os.environ)
    if config.tessdata_prefix:
        env["TESSDATA_PREFIX"] = config.tessdata_prefix

    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "-l", config.language,
        _MODE_FLAGS[config.mode],
        "--oversample", str(config.oversample),
        "--output-type", "pdf",
        "--optimize", str(config.optimize),
        "--quiet",
        str(src), str(out),
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0 or not out.exists():
        raise DependencyError(
            f"OCR failed for {src.name} (ocrmypdf exited {res.returncode}). This usually "
            f"means Tesseract or the {config.language!r} language pack is not installed. "
            f"ocrmypdf's own error:\n{res.stderr[-800:]}"
        )
    return out
