"""Synthetic fixtures for testing pdf.layout / pdf.inkstyle / pdf.clearing
/ pdf.render without any real (confidential) source document.

Two kinds of fixture, deliberately:

1. Hand-built span/line/block dicts, matching the exact shape
   `page.get_text("dict")` produces. These give precise, deterministic
   control over geometry -- which is what's needed to pin a regression
   like "two adjacent lines get welded into one paragraph reading
   'Municipality Address' instead of two column values", or "an OCR
   heading fragments into spurious per-word runs because sizes jitter by
   a few hundredths of a point". Trying to coerce PyMuPDF's own text
   layout analyzer into a specific block/line grouping via `insert_text`
   calls is fragile and version-dependent; constructing the intermediate
   dicts directly is not.

2. Real `fitz.Document` builders, used only where the actual rendering
   matters -- bold-weight pixel measurement (`pdf.inkstyle`) and
   artwork-survives-redaction (`pdf.clearing`) both operate on real
   rendered/rasterized page content, so there's no way around building
   one. Base-14 fonts only ("helv", "hebo", ...), so these need no
   external font file and are byte-reproducible across machines.
"""

from __future__ import annotations

import fitz

FLAG_ITALIC = 1 << 1
FLAG_BOLD = 1 << 4


def make_span(
    text: str,
    x: float,
    y: float,
    *,
    font: str = "Helvetica",
    size: float = 11.0,
    bold: bool = False,
    italic: bool = False,
    color: int = 0,
    width: float | None = None,
) -> dict:
    """A span dict shaped like page.get_text("dict")'s spans. `width`
    defaults to a crude but consistent estimate (0.55 * size per char) so
    bbox math in tests is deterministic without needing real font
    metrics."""
    if width is None:
        width = 0.55 * size * max(len(text), 1)
    flags = (FLAG_BOLD if bold else 0) | (FLAG_ITALIC if italic else 0)
    return {
        "text": text,
        "font": font,
        "size": size,
        "flags": flags,
        "color": color,
        "origin": (x, y),
        "bbox": (x, y - size, x + width, y + size * 0.25),
    }


def make_line(spans: list[dict]) -> dict:
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)
    return {"bbox": (x0, y0, x1, y1), "spans": spans}


def make_block(lines: list[dict]) -> dict:
    x0 = min(ln["bbox"][0] for ln in lines)
    y0 = min(ln["bbox"][1] for ln in lines)
    x1 = max(ln["bbox"][2] for ln in lines)
    y1 = max(ln["bbox"][3] for ln in lines)
    return {"type": 0, "bbox": (x0, y0, x1, y1), "lines": lines}


# ---------------------------------------------------------------------------
# Named regression fixtures
# ---------------------------------------------------------------------------


def two_column_header_row(y: float = 50.0) -> dict:
    """A header row split into two same-row line fragments with a wide
    (column-gutter-sized) gap between them. Regression for a real bug: a
    naive extractor welded 'Direccion' and 'Municipio' into one paragraph
    reading 'Municipality Address' because it didn't distinguish a wide
    column gutter from an ordinary word gap."""
    left = make_line([make_span("Direccion", 50.0, y)])
    right = make_line([make_span("Municipio", 250.0, y)])
    return {"left": left, "right": right}


def two_column_data_row(y: float = 70.0) -> dict:
    left = make_line([make_span("Avenida Ecologica", 50.0, y)])
    right = make_line([make_span("SANTO DOMINGO ESTE", 250.0, y)])
    return {"left": left, "right": right}


def size_jitter_heading_spans() -> list[dict]:
    """Three spans of one physical heading at near-identical but not
    exactly equal sizes -- reproduces OCR reporting a slightly different
    bbox-derived size per WORD on a single visual line. Without
    `_SIZE_JITTER_TOL`, these fragment into three separate style runs;
    that fragmentation is the documented root cause of a real corpus bug
    where the first word of a company name was translated in isolation.
    """
    return [
        make_span("GRUPO ", 50.0, 100.0, size=10.80, bold=True),
        make_span("MERIDIAN, ", 90.0, 100.0, size=10.89, bold=True),
        make_span("SRL.", 170.0, 100.0, size=11.19, bold=True),
    ]


def ordinal_clause_lines() -> list[dict]:
    """A list-item continuation immediately followed by a spelled-out
    legal ordinal heading, both in plain body weight/size -- the case
    `ordinals.HEADING_RE` exists to catch as a paragraph break, since
    nothing about size or boldness distinguishes the heading here."""
    return [
        make_line([make_span("a) el arrendatario pagara el deposito", 50.0, 120.0)]),
        make_line([make_span("DECIMO CUARTO. Las partes acuerdan que", 50.0, 138.0)]),
    ]


def bullet_row(bullet_x: float = 50.0, text_x: float = 65.0, y: float = 150.0) -> list[dict]:
    """A bullet glyph and its item body as two same-row fragments with a
    gutter gap wide enough that `merge_row_fragments`'s ordinary gap
    threshold would treat them as separate columns -- except a bullet is
    always merged with the text that follows it regardless of gap width."""
    return [
        make_line([make_span("•", bullet_x, y, width=6.0)]),
        make_line([make_span("Primer punto de la lista", text_x, y)]),
    ]


# ---------------------------------------------------------------------------
# Real fitz.Document builders
# ---------------------------------------------------------------------------


def bold_vs_regular_page(size: float = 14.0) -> fitz.Document:
    """One page, two lines: one drawn with the base-14 bold face, one
    with the regular face, same size -- ground truth for
    `pdf.inkstyle.stem_ratio` bold/regular discrimination that doesn't
    depend on any particular corpus's calibration, just on regular vs.
    bold actually measuring differently."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=150)
    page.insert_text((20, 50), "Regular weight text sample", fontsize=size, fontname="helv")
    page.insert_text((20, 90), "Bold weight text sample", fontsize=size, fontname="hebo")
    return doc


def page_with_artwork(text: str = "Texto original en espanol") -> fitz.Document:
    """A page with a drawn rectangle (vector line art), an inserted
    image, and overlapping text -- direct regression fixture for the
    redaction defect `pdf.clearing` exists to prevent: a naive
    `apply_redactions()` call with default flags punches through both the
    image and the vector art wherever a redaction rectangle overlaps
    them."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    # Vector line art: a border rectangle.
    page.draw_rect(fitz.Rect(10, 10, 390, 290), color=(0, 0, 0), width=2.0)
    # A small raster image (solid-colour PNG built in-memory via fitz).
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(20, 20, 60, 60), pixmap=pix)
    # Overlapping text -- this is what gets redacted.
    page.insert_text((80, 100), text, fontsize=14, fontname="helv")
    return doc


def simple_paragraph_page(text: str = "Este es un parrafo de prueba en espanol.") -> fitz.Document:
    """A minimal single-paragraph real page, for extract_paragraphs smoke
    tests and the extract -> clear -> draw -> re-extract round trip."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), text, fontsize=12, fontname="helv", align=0,
    )
    return doc
