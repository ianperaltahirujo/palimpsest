"""Render source and output pages side by side for visual QA.

`side_by_side()` takes its destination path as an explicit argument
rather than owning a fixed output directory of its own -- an earlier
version of this module ran `os.makedirs(OUTDIR)` as an import-time side
effect, which `test_no_import_side_effects.py` forbids (see
`core.logging`'s module docstring for the matching fix to the
`sys.stdout.reconfigure` side effect this project's CLI modules used to
have).
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def render_page(path: str | Path, pno: int, dpi: int = 110) -> Image.Image:
    doc = fitz.open(str(path))
    try:
        pm = doc[pno].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    finally:
        doc.close()


def side_by_side(
    src: str | Path,
    out: str | Path,
    pages: list[int],
    dest: Path,
    dpi: int = 110,
    labels: tuple[str, str] = ("SOURCE", "OUTPUT"),
) -> Path:
    """Render `pages` (0-indexed) of `src` and `out` side by side, stacked
    vertically if more than one page, and save to `dest`."""
    tiles = []
    for pno in pages:
        a, b = render_page(src, pno, dpi), render_page(out, pno, dpi)
        gap, hdr = 18, 26
        w = a.width + b.width + gap
        h = max(a.height, b.height) + hdr
        canvas = Image.new("RGB", (w, h), "#9aa0a6")
        canvas.paste(a, (0, hdr))
        canvas.paste(b, (a.width + gap, hdr))
        draw = ImageDraw.Draw(canvas)
        draw.text((6, 7), f"{labels[0]}  p{pno + 1}", fill="#000")
        draw.text((a.width + gap + 6, 7), f"{labels[1]}  p{pno + 1}", fill="#000")
        tiles.append(canvas)

    width = max(t.width for t in tiles)
    height = sum(t.height for t in tiles) + 10 * (len(tiles) - 1)
    sheet = Image.new("RGB", (width, height), "#5f6368")
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + 10

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)
    return dest


def build_dual_pdf(src: str | Path, out: str | Path, dest: Path) -> Path:
    """Interleave source and translated pages into one bilingual PDF --
    source page 1, translated page 1, source page 2, ... -- via
    `Document.insert_pdf` so both stay real vector pages, never
    rasterized. Not the default `translate` output: a replica (same
    pages, only the words changed) IS the default; this is an explicit
    opt-in (`--dual`) for reviewing a translation against its source
    page by page."""
    src_doc = fitz.open(str(src))
    out_doc = fitz.open(str(out))
    try:
        n = min(len(src_doc), len(out_doc))
        dual = fitz.open()
        try:
            for i in range(n):
                dual.insert_pdf(src_doc, from_page=i, to_page=i)
                dual.insert_pdf(out_doc, from_page=i, to_page=i)
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dual.save(dest)
        finally:
            dual.close()
        return dest
    finally:
        src_doc.close()
        out_doc.close()
