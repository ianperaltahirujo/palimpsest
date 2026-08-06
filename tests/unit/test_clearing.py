import fitz

from palimpsest.pdf import clearing
from tests.fixtures import synth


def _text_block_rects(page: fitz.Page) -> list[fitz.Rect]:
    blocks = page.get_text("dict")["blocks"]
    return [fitz.Rect(b["bbox"]) for b in blocks if b.get("type") == 0]


def test_safe_flags_never_touch_images_or_line_art():
    """Pin the exact defect this module exists to prevent: the SAFE flags
    must be PDF_REDACT_IMAGE_NONE / PDF_REDACT_LINE_ART_NONE, not
    PyMuPDF's default (images=2, graphics=1), which punch through a
    scanned page's artwork wherever a redaction rectangle overlaps it."""
    assert clearing.SAFE["images"] == fitz.PDF_REDACT_IMAGE_NONE
    assert clearing.SAFE["graphics"] == fitz.PDF_REDACT_LINE_ART_NONE
    assert clearing.SAFE["text"] == fitz.PDF_REDACT_TEXT_REMOVE


def test_clear_text_digital_removes_the_text():
    doc = synth.page_with_artwork("Texto original en espanol")
    page = doc[0]
    before = page.get_text()
    assert "Texto original" in before

    text_rects = _text_block_rects(page)
    clearing.clear_text_digital(page, text_rects)

    after = page.get_text()
    assert "Texto original" not in after


def test_clear_text_digital_preserves_vector_line_art():
    doc = synth.page_with_artwork()
    page = doc[0]
    drawings_before = len(page.get_drawings())
    assert drawings_before > 0

    text_rects = _text_block_rects(page)
    clearing.clear_text_digital(page, text_rects)

    drawings_after = len(page.get_drawings())
    assert drawings_after == drawings_before


def test_clear_text_digital_preserves_images():
    doc = synth.page_with_artwork()
    page = doc[0]
    images_before = len(page.get_images(full=True))
    assert images_before > 0

    text_rects = _text_block_rects(page)
    clearing.clear_text_digital(page, text_rects)

    images_after = len(page.get_images(full=True))
    assert images_after == images_before


def test_clear_text_digital_empty_rects_is_a_noop():
    doc = synth.page_with_artwork()
    page = doc[0]
    assert clearing.clear_text_digital(page, []) == 0


def test_inpaint_scanned_returns_zero_when_no_dominant_image():
    """A page with only a small logo-sized image (not covering most of
    the page) must not be treated as 'the scan' -- inpainting a small
    incidental image would corrupt it for no benefit."""
    doc = synth.page_with_artwork()  # the image here is only 40x40 on a 400x300 page
    page = doc[0]
    filled = clearing.inpaint_scanned(page, [fitz.Rect(80, 90, 300, 115)])
    assert filled == 0


def test_inpaint_scanned_empty_rects_is_a_noop():
    doc = synth.page_with_artwork()
    assert clearing.inpaint_scanned(doc[0], []) == 0
