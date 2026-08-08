"""Regenerate a translated page's drawn text from edit-mode's JSON.

Why "clear and redraw every paragraph", not just the touched ones
-------------------------------------------------------------------
The edit-mode payload (`web/prototype/src/edit/useEditBoxes.js`'s
`exportPayload`) is a list of paragraphs in the SAME order the browser
got them from `GET /jobs/{id}/layout`, each tagged "kept" / "modified" /
"deleted". That order and those rects are only guaranteed to still match
reality if nothing has redrawn the page since -- which is exactly what
this module does. Re-running `pdf.layout.extract_paragraphs` right
before redrawing, and indexing into the edit payload by that FRESH
paragraph order rather than trusting rects the client sent, is what
makes this endpoint safe to call more than once for the same page: each
call's "kept" paragraphs are redrawn from what the page actually
contains right now, not from a stale snapshot.

Every paragraph on the page is cleared, including the ones being kept
unchanged, and everything is redrawn in one pass. A partial clear (only
the "modified" ones) would leave "kept" paragraphs unexplained by this
module's own idea of the page and double the number of code paths that
have to agree on paragraph order.

Digital PDFs only -- same constraint edit mode already documents (the
overlay masks previously-drawn text with flat paper, which only reads
correctly against a real text layer, not a scan's photographed paper).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import fitz

from palimpsest.config.model import Config
from palimpsest.pdf import layout
from palimpsest.pdf.fontmap import FontResolver
from palimpsest.pdf.render import (
    HIGHLIGHT_DROP,
    HIGHLIGHT_RISE,
    UNDERLINE_OFFSET,
    UNDERLINE_THICKNESS,
    RenderContext,
    draw_paragraph,
)

# Reflow-specific clearing, deliberately stronger than the main
# pipeline's `clearing.clear_text_digital`
# ---------------------------------------------------------------------
# `clear_text_digital` never touches vector graphics, on purpose: a
# decorative rule or table border under a paragraph must survive the
# ordinary translate pass untouched (see its docstring). Reflow is
# different -- it is the ONLY code path that ever draws vector marks of
# its own (the underline stroke and highlight rect in
# `pdf.render.draw_paragraph`, only ever populated from edit-mode runs;
# see `core.ir.Run`), so it needs to be able to remove its own prior
# marks when an edit turns a highlight or underline back off. Using
# REMOVE_IF_COVERED rather than a blanket REMOVE keeps the blast radius
# to marks entirely inside the redacted paragraph box -- our own marks
# always are, by construction (`render.py`'s per-word geometry never
# exceeds the paragraph rect it was drawn into) -- while a rule or
# border that extends past the box's own edge is left alone.
_REFLOW_REDACT = dict(
    images=fitz.PDF_REDACT_IMAGE_NONE,
    graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
    text=fitz.PDF_REDACT_TEXT_REMOVE,
)


def _clear_for_reflow(page: fitz.Page, rects: list[fitz.Rect]) -> None:
    if not rects:
        return
    for r in rects:
        page.add_redact_annot(fitz.Rect(r), fill=False)
    page.apply_redactions(**_REFLOW_REDACT)


def build_render_context(config: Config, rel: str) -> RenderContext:
    """Same construction `pdf.pipeline.translate_pdf_document` uses --
    reflow needs a fresh one per call since fonts/thresholds can change
    between edits (e.g. a config reload), and font resolution is cheap
    relative to a user's edit-and-save cadence."""
    font_resolver = FontResolver(
        extra_dirs=config.fonts.extra_dirs, use_bundled_fallback=config.fonts.use_bundled_fallback,
    )
    return RenderContext(
        font_resolver=font_resolver,
        default_scan_family=config.fonts.per_document.get(rel, config.fonts.scan_default),
        min_scale=config.thresholds.min_scale,
        justify_max_stretch=config.thresholds.justify_max_stretch,
    )


def _kept_segments(para: layout.Para) -> list[tuple[str, tuple]]:
    return [(r["text"], r["style"]) for r in para.runs if r["text"].strip()]


def _style_from_edited_run(run: dict, font: str, size: float) -> tuple:
    color = tuple(run.get("color") or (0.0, 0.0, 0.0))
    highlight = run.get("highlight")
    return (
        font, size,
        bool(run.get("bold", False)), bool(run.get("italic", False)), color,
        bool(run.get("underline", False)), tuple(highlight) if highlight else None,
    )


_CLEAR_EPSILON = 0.75  # points; absorbs draw-vs-extract width rounding, see below


def _padded_clear_rect(para: layout.Para) -> fitz.Rect:
    """`extract_paragraphs` reports a paragraph's TEXT bounding box, which
    is tighter than the highlight rect / underline stroke `render.py`
    draws around a word (those are sized off the font size, not measured
    ink extents). Padding the clear rect vertically by the same
    constants render.py uses to draw those marks is what makes
    `_clear_for_reflow` actually remove a mark from a prior reflow call
    -- clearing the bare text bbox left the highlight rect's top edge
    uncovered and REMOVE_IF_COVERED only removes graphics fully inside
    the redacted rect. A small horizontal `_CLEAR_EPSILON` is needed too:
    a word's highlight width comes from `RenderContext.measure` at draw
    time, while the "current" rect here comes from PyMuPDF's own glyph
    bbox on re-extraction -- the two disagree by hundredths of a point,
    enough for REMOVE_IF_COVERED to call a highlight "not fully covered"
    and leave it behind."""
    r = fitz.Rect(para.rect)
    r.x0 -= _CLEAR_EPSILON
    r.x1 += _CLEAR_EPSILON
    r.y0 -= para.size * HIGHLIGHT_RISE
    r.y1 += para.size * max(HIGHLIGHT_DROP, UNDERLINE_OFFSET + UNDERLINE_THICKNESS)
    return r


def _rect_from_dict(d: dict | None, fallback: fitz.Rect) -> fitz.Rect:
    if not d:
        return fallback
    return fitz.Rect(
        d.get("x0", fallback.x0), d.get("y0", fallback.y0),
        d.get("x1", fallback.x1), d.get("y1", fallback.y1),
    )


def apply_page_edits(
    output_path: Path,
    page_no: int,
    edited_paragraphs: list[dict[str, Any]],
    render_ctx: RenderContext,
) -> dict:
    """Clear and redraw one page of `output_path` in place from an
    edit-mode payload's paragraph list.

    `edited_paragraphs[i]` is matched against the i-th paragraph
    `pdf.layout.extract_paragraphs` finds on the page right now -- see
    the module docstring for why that, not the client's rects, is the
    source of truth for ordering. A paragraph missing from the payload
    (the list is shorter than what's on the page) is treated as "kept".

    Returns `{"page", "paragraphs", "redrawn"}`. Raises `OSError` if the
    rewritten file can't be written -- callers should treat that as a
    500, not swallow it, since the alternative is silently pretending
    the edit was applied.
    """
    doc = fitz.open(str(output_path))
    try:
        page = doc[page_no]
        current = layout.extract_paragraphs(page, min_size=3.0)
        _clear_for_reflow(page, [_padded_clear_rect(p) for p in current])
        obstacles = layout.page_obstacle_rects(page)

        redrawn = 0
        for i, cur_para in enumerate(current):
            edit = edited_paragraphs[i] if i < len(edited_paragraphs) else None
            op = (edit or {}).get("edit", "kept")
            if op == "deleted":
                continue

            if op != "modified" or edit is None:
                segs = _kept_segments(cur_para)
                if not segs:
                    continue
                avail = layout.available_rect(page, cur_para, current, obstacles=obstacles)
                draw_paragraph(render_ctx, page, cur_para, segs, avail)
                redrawn += 1
                continue

            font = edit.get("font") or cur_para.font
            size = float(edit.get("size") or cur_para.size)
            runs = edit.get("runs") or []
            segs = [
                (r["text"], _style_from_edited_run(r, font, size))
                for r in runs if (r.get("text") or "").strip()
            ]
            if not segs:
                continue
            rect = _rect_from_dict(edit.get("rect"), cur_para.rect)
            origin = tuple(edit.get("origin") or cur_para.origin)
            leading = edit.get("leading") or cur_para.leading or size * 1.18
            para_like = SimpleNamespace(
                align=edit.get("align", cur_para.align),
                size=size,
                leading=float(leading),
                origin=origin,
                rect=rect,
                # A moved/resized box no longer honours the source's
                # hanging indent -- there is no longer a stable relation
                # between the box's new left edge and where a hanging
                # bullet/enumerator used to sit.
                hang_x0=None,
            )
            draw_paragraph(render_ctx, page, para_like, segs, rect, align=para_like.align)
            redrawn += 1

        tmp_path = output_path.with_name(output_path.name + ".reflow.tmp")
        doc.save(str(tmp_path), garbage=4, deflate=True)
    finally:
        doc.close()
    # Close before replacing -- an open fitz.Document holds the file
    # locked on Windows, so save-then-replace has to happen in that
    # order, not save-over-the-open-path (which PyMuPDF refuses anyway
    # for a document opened from that same path).
    tmp_path.replace(output_path)
    return {"page": page_no, "paragraphs": len(current), "redrawn": redrawn}
