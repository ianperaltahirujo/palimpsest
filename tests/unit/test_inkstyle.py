import fitz

from palimpsest.pdf import inkstyle
from palimpsest.pdf.layout import Para
from tests.fixtures import synth

STYLE = ("helv", 14.0, False, False, (0, 0, 0))


def _make_para(text: str, rect: fitz.Rect, origin: tuple[float, float]) -> Para:
    return Para(
        runs=[{"text": text, "style": STYLE}], text=text, rect=rect,
        line_rects=[rect], block_no=0, origin=origin, clip=None, hang_x0=None,
        align="left", leading=16.0, size=14.0, font="helv", color=(0, 0, 0),
        page=0, indent=0.0,
    )


def test_page_ink_map_shape_matches_scaled_page_size():
    doc = synth.bold_vs_regular_page()
    arr, scale = inkstyle.page_ink_map(doc[0], dpi=150)
    assert scale == 150 / 72.0
    assert arr.shape[0] > 0 and arr.shape[1] > 0


def test_stem_ratio_none_when_region_has_too_little_ink():
    doc = synth.bold_vs_regular_page()
    arr, scale = inkstyle.page_ink_map(doc[0])
    # An empty region far from any drawn text.
    empty_rect = fitz.Rect(250, 5, 295, 15)
    assert inkstyle.stem_ratio(arr, scale, empty_rect, size=14.0) is None


def test_bold_text_measures_a_larger_stem_ratio_than_regular():
    """The core empirical claim this module rests on: real bold text
    measures a distinguishably thicker stem than real regular text at the
    same size. Not asserting a specific corpus-fitted threshold here --
    that's covered by docs/design/bold-calibration.md -- just that the
    signal exists and points the right direction."""
    doc = synth.bold_vs_regular_page(size=14.0)
    page = doc[0]
    arr, scale = inkstyle.page_ink_map(page)

    regular_rect = fitz.Rect(18, 38, 220, 55)
    bold_rect = fitz.Rect(18, 78, 220, 95)

    regular_ratio = inkstyle.stem_ratio(arr, scale, regular_rect, size=14.0)
    bold_ratio = inkstyle.stem_ratio(arr, scale, bold_rect, size=14.0)

    assert regular_ratio is not None
    assert bold_ratio is not None
    assert bold_ratio > regular_ratio


def test_annotate_bold_marks_paragraph_measured_as_bold():
    doc = synth.bold_vs_regular_page(size=14.0)
    page = doc[0]
    bold_rect = fitz.Rect(18, 78, 220, 95)
    para = _make_para("Bold weight text sample", bold_rect, (20.0, 90.0))
    # The packaged default (0.155) was fitted against a specific real
    # corpus's bold font; base-14 Helvetica-Bold measures ~0.154 here,
    # just under it. Use a threshold appropriate to THIS synthetic font
    # to test annotate_bold's marking behavior itself, not the packaged
    # calibration (that's covered by test_bold_text_measures_a_larger_
    # stem_ratio_than_regular, which asserts the direction without
    # depending on any specific threshold).
    thresholds = inkstyle.InkThresholds(bold_stem_ratio=0.13)
    marked = inkstyle.annotate_bold(page, [para], thresholds=thresholds)
    assert marked == 1
    assert para.runs[0]["style"][2] is True  # bold flag set


def test_annotate_bold_does_not_mark_regular_paragraph():
    doc = synth.bold_vs_regular_page(size=14.0)
    page = doc[0]
    regular_rect = fitz.Rect(18, 38, 220, 55)
    para = _make_para("Regular weight text sample", regular_rect, (20.0, 50.0))
    marked = inkstyle.annotate_bold(page, [para])
    assert marked == 0
    assert para.runs[0]["style"][2] is False


def test_annotate_bold_empty_paras_returns_zero():
    doc = synth.bold_vs_regular_page()
    assert inkstyle.annotate_bold(doc[0], []) == 0


def test_ink_thresholds_dataclass_defaults_match_module_constants():
    t = inkstyle.InkThresholds()
    assert t.dpi == inkstyle.DPI
    assert t.bold_stem_ratio == inkstyle.BOLD_STEM_RATIO
