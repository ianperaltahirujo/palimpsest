import fitz
import pytest

from palimpsest.pdf.classify import classify_pdf
from tests.fixtures.synth import simple_paragraph_page


def test_digital_pdf_with_real_text(tmp_path):
    doc = simple_paragraph_page(
        "Este es un texto suficientemente largo para no parecer un escaneo."
    )
    path = tmp_path / "digital.pdf"
    doc.save(path)
    doc.close()
    assert classify_pdf(str(path)) == "digital"


def test_scan_pdf_with_no_text_layer(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(fitz.Rect(0, 0, 300, 300), pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    doc.close()
    assert classify_pdf(str(path)) == "scan"


def test_ocr_pdf_with_glyphless_font(tmp_path, monkeypatch):
    """A real OCR text layer names every font 'GlyphLessFont' and carries
    no real typeface -- classify_pdf must distinguish this from a
    genuinely digital PDF. Faked via monkeypatch since embedding a real
    font under that name needs a font FILE this repo doesn't bundle yet
    (see pdf/fontmap.py's documented deferral)."""
    doc = simple_paragraph_page("Suficiente texto para superar el umbral de caracteres por pagina.")
    path = tmp_path / "ocr.pdf"
    doc.save(path)
    doc.close()

    monkeypatch.setattr(
        fitz.Page, "get_fonts", lambda self, full=False: [(0, "", "", "GlyphLessFont")]
    )
    assert classify_pdf(str(path)) == "ocr"


def test_empty_pdf_is_not_scan():
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "empty.pdf"
        doc.save(path)
        doc.close()
        # No text, no fonts at all -- classified as scan (0 chars < 40 * 1 page).
        assert classify_pdf(str(path)) == "scan"


@pytest.mark.parametrize("chars_per_page", [0, 39])
def test_below_char_threshold_is_scan(tmp_path, monkeypatch, chars_per_page):
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    path = tmp_path / "sparse.pdf"
    doc.save(path)
    doc.close()

    monkeypatch.setattr(fitz.Page, "get_text", lambda self, *a, **kw: "x" * chars_per_page)
    assert classify_pdf(str(path)) == "scan"
