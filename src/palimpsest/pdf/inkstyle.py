"""Recover typographic weight from a scanned page's pixels.

Why this is needed
-------------------
OCR tooling writes its text layer in a placeholder font carrying position
and codepoints only -- no family, no weight, no style. So on a scanned
document there is nothing in the text layer to say that a whole
paragraph is set in bold.

The ink is still in the raster. Weight is recovered by measuring stem
width: for each row of pixels across a line, the lengths of consecutive
dark runs are collected, and their median approximates the vertical stem
thickness. Dividing by the type size gives a scale-free number that is
roughly 0.10-0.12 for regular text and 0.17-0.19 for bold.

Calibration
-----------
The default threshold below (0.155) is not a universal constant -- it was
fitted against ground truth from a specific corpus: 1,152 text lines from
four DIGITAL source PDFs, where the true weight is known from the
embedded font names. Measured at 300 DPI:

    regular   p50 = 0.117   p90 = 0.144   p95 = 0.160
    bold      p05 = 0.155   p10 = 0.160   p50 = 0.195

    threshold  bold recall   falsely bold
      0.130       100%           16.0%
      0.155        95%            7.3%     <- chosen (the knee of the curve)
      0.160        89%            4.8%

It is deliberately an ABSOLUTE threshold, not one relative to the page: a
relative rule breaks on exactly the case that matters most -- a document
that is bold nearly throughout, where the page median IS bold and so
nothing stands out against it. (That was the first approach tried, and it
detected almost no bold on a corpus letter that was in fact bold body
text.)

See docs/design/bold-calibration.md for the full writeup. If your
documents behave differently, re-fit and override via
`[thresholds].bold_stem_ratio` in your palimpsest.toml rather than editing
this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz
import numpy as np

DPI = 300
DARK = 165  # 0-255; below this a pixel counts as ink
BOLD_STEM_RATIO = 0.155
MIN_INK_PIXELS = 60
MIN_RUNS = 20


def page_ink_map(page: fitz.Page, dpi: int = DPI) -> tuple[np.ndarray, float]:
    """Greyscale pixels of the page plus the PDF->pixel scale factor."""
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
    return arr, dpi / 72.0


def stem_ratio(
    arr: np.ndarray,
    scale: float,
    rect: fitz.Rect,
    size: float,
    pad: float = 0.5,
    dark: int = DARK,
    min_ink_pixels: int = MIN_INK_PIXELS,
    min_runs: int = MIN_RUNS,
) -> float | None:
    """Median horizontal ink-run length divided by type size. None if the
    region holds too little ink to measure reliably."""
    if size <= 0:
        return None
    h, w = arr.shape
    x0 = max(0, int((rect.x0 - pad) * scale))
    x1 = min(w, int((rect.x1 + pad) * scale))
    y0 = max(0, int((rect.y0 - pad) * scale))
    y1 = min(h, int((rect.y1 + pad) * scale))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    patch = arr[y0:y1, x0:x1] < dark
    if patch.sum() < min_ink_pixels:
        return None
    runs = []
    for row in patch:
        if not row.any():
            continue
        # Run boundaries via the diff of the 0-padded row.
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        runs.extend((idx[1::2] - idx[0::2]).tolist())
    runs = [r for r in runs if r > 0]
    if len(runs) < min_runs:
        return None
    return float(np.median(runs)) / (size * scale)


@dataclass(frozen=True)
class InkThresholds:
    """Bundles the tunables so callers can pass one object sourced from
    `config.ThresholdsConfig` instead of five loose keyword args."""

    dpi: int = DPI
    dark: int = DARK
    bold_stem_ratio: float = BOLD_STEM_RATIO
    min_ink_pixels: int = MIN_INK_PIXELS
    min_runs: int = MIN_RUNS


def detect_bullets(page: fitz.Page, paras, gutter: float = 30.0, min_ink: int = 12) -> int:
    """Flag paragraphs that a bullet glyph introduces, by looking for ink
    in the gutter immediately to their left.

    OCR frequently does not transcribe bullet characters at all -- the
    bullet exists only as ink in the scan, with no codepoint anywhere in
    the text layer. Without this, consecutive list items look like
    ordinary consecutive lines and get merged into one run-on paragraph,
    leaving a column of orphaned bullets down the page.

    Returns the number of paragraphs flagged. Sets `starts_item` on each.
    """
    for p in paras:
        p.starts_item = False
    if not paras:
        return 0
    arr, scale = page_ink_map(page)
    h, w = arr.shape
    found = 0
    for p in paras:
        first = p.line_rects[0] if p.line_rects else p.rect
        x1 = int((first.x0 - 3.0) * scale)
        x0 = int((first.x0 - gutter) * scale)
        y0 = int(first.y0 * scale)
        y1 = int(first.y1 * scale)
        x0, x1 = max(0, x0), min(w, x1)
        y0, y1 = max(0, y0), min(h, y1)
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        patch = arr[y0:y1, x0:x1] < DARK
        ink = int(patch.sum())
        if ink < min_ink:
            continue
        # A table rule or cell border spans the full height of the band;
        # a bullet is a small blob. Reject anything that inks every row.
        rows_with_ink = int(patch.any(axis=1).sum())
        if rows_with_ink >= (y1 - y0) * 0.9:
            continue
        p.starts_item = True
        found += 1
    return found


def annotate_bold(page: fitz.Page, paras, thresholds: InkThresholds | None = None) -> int:
    """Set the bold flag on each paragraph's runs from measured stem
    width. Returns the number of paragraphs marked bold."""
    if not paras:
        return 0
    thresholds = thresholds or InkThresholds()
    arr, scale = page_ink_map(page, dpi=thresholds.dpi)
    marked = 0
    for p in paras:
        r = stem_ratio(
            arr, scale, p.rect, p.size,
            dark=thresholds.dark,
            min_ink_pixels=thresholds.min_ink_pixels,
            min_runs=thresholds.min_runs,
        )
        if r is None or r < thresholds.bold_stem_ratio:
            continue
        for run in p.runs:
            font, size, _bold, ital, color = run["style"]
            run["style"] = (font, size, True, ital, color)
        marked += 1
    return marked
