"""Unit tests for `pdf.reflow.apply_page_edits`, independent of the
FastAPI layer -- see test_server_api.py for the full PATCH /layout
HTTP-level test."""

from __future__ import annotations

from pathlib import Path

import fitz

from palimpsest.config.model import Config, FontsConfig, PathsConfig, ThresholdsConfig
from palimpsest.pdf import layout
from palimpsest.pdf.reflow import apply_page_edits, build_render_context


def _config(tmp_path: Path) -> Config:
    return Config(
        paths=PathsConfig(
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
            report_dir=tmp_path / "reports",
        ),
        thresholds=ThresholdsConfig(),
        fonts=FontsConfig(use_bundled_fallback=True),
    )


def _make_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 90), "First paragraph text here.", fontsize=12, fontname="helv"
    )
    page.insert_textbox(
        fitz.Rect(40, 120, 360, 170), "Second paragraph text here.", fontsize=12, fontname="helv"
    )
    path = tmp_path / "doc.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _base_edit(para: layout.Para) -> dict:
    return {
        "font": para.font, "size": para.size, "align": para.align, "leading": para.leading,
        "rect": {"x0": para.rect.x0, "y0": para.rect.y0, "x1": para.rect.x1, "y1": para.rect.y1},
        "origin": list(para.origin),
    }


def test_no_edits_redraws_every_paragraph_kept_and_unchanged(tmp_path):
    path = _make_pdf(tmp_path)
    ctx = build_render_context(_config(tmp_path), "doc.pdf")
    result = apply_page_edits(path, 0, [], ctx)
    assert result == {"page": 0, "paragraphs": 2, "redrawn": 2}

    doc = fitz.open(str(path))
    text = doc[0].get_text()
    doc.close()
    assert "First paragraph" in text
    assert "Second paragraph" in text


def test_modified_paragraph_text_is_replaced_in_the_pdf(tmp_path):
    path = _make_pdf(tmp_path)
    ctx = build_render_context(_config(tmp_path), "doc.pdf")
    doc = fitz.open(str(path))
    para0 = layout.extract_paragraphs(doc[0])[0]
    doc.close()

    edit = {
        **_base_edit(para0), "edit": "modified",
        "runs": [{"text": "Replaced text", "bold": False, "italic": False,
                   "underline": False, "highlight": None, "color": [0, 0, 0]}],
    }
    result = apply_page_edits(path, 0, [edit], ctx)
    assert result["redrawn"] == 2

    doc = fitz.open(str(path))
    text = doc[0].get_text()
    doc.close()
    assert "Replaced text" in text
    assert "First paragraph" not in text
    assert "Second paragraph" in text  # untouched, still "kept"


def test_deleted_paragraph_is_removed_and_not_redrawn(tmp_path):
    path = _make_pdf(tmp_path)
    ctx = build_render_context(_config(tmp_path), "doc.pdf")
    result = apply_page_edits(path, 0, [{"edit": "deleted"}], ctx)
    assert result["redrawn"] == 1  # only the second, kept paragraph

    doc = fitz.open(str(path))
    text = doc[0].get_text()
    doc.close()
    assert "First paragraph" not in text
    assert "Second paragraph" in text


def test_turning_a_highlight_off_on_a_second_reflow_call_actually_removes_it(tmp_path):
    """Regression test for the reason reflow's clearing pass is stronger
    than the main pipeline's `clearing.clear_text_digital`: the
    highlight rect drawn by an earlier reflow is vector graphics, not
    text, so a text-only clear would leave it orphaned behind whatever
    gets redrawn next."""
    path = _make_pdf(tmp_path)
    ctx = build_render_context(_config(tmp_path), "doc.pdf")
    doc = fitz.open(str(path))
    para0 = layout.extract_paragraphs(doc[0])[0]
    doc.close()

    highlighted = {
        **_base_edit(para0), "edit": "modified",
        "runs": [{"text": "Marked text", "bold": False, "italic": False,
                   "underline": False, "highlight": [1.0, 0.9, 0.5], "color": [0, 0, 0]}],
    }
    apply_page_edits(path, 0, [highlighted], ctx)
    doc = fitz.open(str(path))
    fills = [d["fill"] for d in doc[0].get_drawings() if d.get("fill")]
    doc.close()
    assert fills, "expected the highlight rect to be drawn"

    unhighlighted = {
        **_base_edit(para0), "edit": "modified",
        "runs": [{"text": "Marked text", "bold": False, "italic": False,
                   "underline": False, "highlight": None, "color": [0, 0, 0]}],
    }
    apply_page_edits(path, 0, [unhighlighted], ctx)
    doc = fitz.open(str(path))
    fills_after = [d["fill"] for d in doc[0].get_drawings() if d.get("fill")]
    doc.close()
    assert not fills_after, "the old highlight rect must not survive a reflow that removes it"


def test_reflow_does_not_touch_vector_art_outside_any_paragraph_rect(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 90), "First paragraph text here.", fontsize=12, fontname="helv"
    )
    page.draw_rect(fitz.Rect(10, 200, 390, 210), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    path = tmp_path / "doc.pdf"
    doc.save(str(path))
    doc.close()

    ctx = build_render_context(_config(tmp_path), "doc.pdf")
    apply_page_edits(path, 0, [], ctx)

    doc = fitz.open(str(path))
    fills = [d["fill"] for d in doc[0].get_drawings() if d.get("fill")]
    doc.close()
    assert fills, "decorative art well outside any paragraph rect must survive reflow"
