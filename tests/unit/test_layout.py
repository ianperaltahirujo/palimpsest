import fitz
import pytest

from palimpsest.pdf import layout
from tests.fixtures import synth

# -- column_bands / merge_row_fragments: the column-merge regression -------

def test_column_bands_splits_two_column_header_row():
    row = synth.two_column_header_row()
    lines = [row["left"], row["right"]]
    bands = layout.column_bands(lines)
    assert len(bands) == 2


def test_column_bands_single_flowing_column_when_no_row_has_two_lines():
    lines = [
        synth.make_line([synth.make_span("Primera linea", 50.0, 50.0)]),
        synth.make_line([synth.make_span("Segunda linea", 50.0, 70.0)]),
    ]
    bands = layout.column_bands(lines)
    assert len(bands) == 1
    assert bands[0][0] is None


def test_merge_row_fragments_keeps_wide_gap_as_two_columns():
    """The real regression: 'Direccion' and 'Municipio' must NOT be
    welded into one paragraph -- the gap between them is column-gutter
    width, not an ordinary word gap."""
    row = synth.two_column_header_row()
    merged = layout.merge_row_fragments([row["left"], row["right"]])
    assert len(merged) == 2
    texts = {layout._line_text(m) for m in merged}
    assert texts == {"Direccion", "Municipio"}


def test_merge_row_fragments_binds_bullet_to_its_text_regardless_of_gap():
    lines = synth.bullet_row()
    merged = layout.merge_row_fragments(lines)
    assert len(merged) == 1
    assert layout._line_text(merged[0]) == "• Primer punto de la lista"


def test_two_column_data_row_stays_split():
    row = synth.two_column_data_row()
    bands = layout.column_bands([row["left"], row["right"]])
    assert len(bands) == 2


# -- _build_runs: the size-jitter / GRUPO->CLUSTER regression --------------

def test_build_runs_merges_jittered_same_style_spans_into_one_run():
    """Without size-jitter tolerance, this heading fragments into three
    runs -- which is the documented mechanism behind a real corpus bug
    where the first word of a company name was translated in isolation."""
    line = synth.make_line(synth.size_jitter_heading_spans())
    runs = layout._build_runs([line])
    assert len(runs) == 1
    assert runs[0]["text"] == "GRUPO MERIDIAN, SRL."


def test_build_runs_respects_jitter_tolerance_parameter():
    line = synth.make_line(synth.size_jitter_heading_spans())
    # A near-zero tolerance should NOT merge spans whose sizes differ by
    # several hundredths of a point.
    runs = layout._build_runs([line], size_jitter_tolerance=0.001)
    assert len(runs) == 3


def test_build_runs_keeps_differently_styled_spans_separate():
    line = synth.make_line([
        synth.make_span("CONSIDERANDO:", 50.0, 50.0, bold=True),
        synth.make_span(" que las partes acuerdan", 150.0, 50.0, bold=False),
    ])
    runs = layout._build_runs([line])
    assert len(runs) == 2
    assert runs[0]["style"][2] is True  # bold
    assert runs[1]["style"][2] is False


# -- ordinals.HEADING_RE as a paragraph-break signal ------------------------

def test_group_lines_splits_on_ordinal_heading_even_at_body_size():
    lines = synth.ordinal_clause_lines()
    block = synth.make_block(lines)
    groups = layout._group_lines_into_paragraphs(block, lines)
    assert len(groups) == 2
    assert layout._line_text(groups[1][0]).startswith("DECIMO CUARTO")


def test_group_lines_splits_on_list_marker():
    lines = [
        synth.make_line([synth.make_span("texto introductorio", 50.0, 50.0)]),
        synth.make_line([synth.make_span("a) primer elemento", 50.0, 68.0)]),
    ]
    block = synth.make_block(lines)
    groups = layout._group_lines_into_paragraphs(block, lines)
    assert len(groups) == 2


def test_group_lines_splits_on_size_change():
    lines = [
        synth.make_line([synth.make_span("Titulo grande", 50.0, 50.0, size=18.0)]),
        synth.make_line([synth.make_span("cuerpo normal", 50.0, 75.0, size=11.0)]),
    ]
    block = synth.make_block(lines)
    groups = layout._group_lines_into_paragraphs(block, lines)
    assert len(groups) == 2


def test_group_lines_keeps_single_line_as_one_group():
    lines = [synth.make_line([synth.make_span("Unica linea", 50.0, 50.0)])]
    block = synth.make_block(lines)
    groups = layout._group_lines_into_paragraphs(block, lines)
    assert len(groups) == 1


# -- _detect_align -----------------------------------------------------------

def test_detect_align_justify_when_left_and_right_edges_agree():
    block_rect = fitz.Rect(50, 0, 350, 100)
    line_rects = [fitz.Rect(50, 0, 350, 15), fitz.Rect(50, 15, 350, 30), fitz.Rect(50, 30, 200, 45)]
    assert layout._detect_align(line_rects, block_rect) == "justify"


def test_detect_align_left_when_only_left_edge_agrees():
    block_rect = fitz.Rect(50, 0, 350, 100)
    line_rects = [fitz.Rect(50, 0, 300, 15), fitz.Rect(50, 15, 250, 30), fitz.Rect(50, 30, 200, 45)]
    assert layout._detect_align(line_rects, block_rect) == "left"


def test_detect_align_center_single_line():
    block_rect = fitz.Rect(0, 0, 400, 50)
    line_rects = [fitz.Rect(150, 0, 250, 15)]
    assert layout._detect_align(line_rects, block_rect) == "center"


def test_detect_align_right_single_line():
    block_rect = fitz.Rect(0, 0, 400, 50)
    line_rects = [fitz.Rect(300, 0, 398, 15)]
    assert layout._detect_align(line_rects, block_rect) == "right"


# -- extract_paragraphs / merge_flowing_paragraphs: real fitz round trip ---

def test_extract_paragraphs_finds_the_paragraph():
    doc = synth.simple_paragraph_page()
    page = doc[0]
    paras = layout.extract_paragraphs(page)
    assert len(paras) >= 1
    joined = " ".join(p.text for p in paras)
    assert "parrafo de prueba" in joined


def test_extract_paragraphs_skips_pure_numeric_lines():
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((20, 50), "123.456", fontsize=12, fontname="helv")
    paras = layout.extract_paragraphs(page)
    assert paras == []


def test_extract_paragraphs_rejects_size_wildly_larger_than_its_own_bbox(monkeypatch):
    """A real regression: OCR misread a few characters of noise out of a
    government seal/QR-code graphic on a scanned document and reported a
    huge inferred font size for it (44.36pt), because that size came from
    the apparent glyph height within the graphic it was misread from, not
    any real font metric -- the bbox stayed tiny (under 19pt), since the
    "glyphs" were small artifacts. Nothing capped the resulting draw size,
    so it rendered as a giant word stamped over a signature block,
    overlapping the page. Real text's size and its own single-line bbox
    height move together; this rejects when they wildly disagree instead
    of trusting the size at face value."""
    span = {
        "text": "DIS", "font": "Helvetica", "size": 44.36, "flags": 0,
        "color": 0, "origin": (210.0, 690.0),
        "bbox": (210.0, 679.8, 439.7, 698.7),  # only ~19pt tall -- not ~44pt
    }
    line = {"bbox": span["bbox"], "spans": [span]}
    block = {"type": 0, "bbox": span["bbox"], "lines": [line]}
    fake_dict = {"blocks": [block]}

    monkeypatch.setattr(fitz.Page, "get_text", lambda self, *a, **kw: fake_dict)
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    assert layout.extract_paragraphs(page) == []


# -- available_rect: table-cell vertical bound (previously untested at all) --

def _para(rect, clip=None) -> layout.Para:
    return layout.Para(
        text="x", runs=[], rect=fitz.Rect(rect), origin=(rect[0], rect[3]),
        align="left", leading=12.0, size=10.0, font="Helvetica",
        color=(0, 0, 0), page=0, indent=0.0, line_rects=[fitz.Rect(rect)],
        block_no=0, clip=fitz.Rect(clip) if clip else None, hang_x0=None,
        starts_item=False,
    )


def test_available_rect_bounded_by_own_clip_with_no_paragraph_below():
    """The exact regression: a table cell whose neighbouring cell in the
    row below has no extracted paragraph of its own (a real cause: it was
    a bare 'N/D' or otherwise didn't qualify as translatable) had nothing
    to stop it growing, so its clip -- the cell's own bottom edge, known
    at extraction time -- must bound it directly instead of falling back
    all the way to the page margin. The paragraph's own rect is narrower
    than its cell (a short line inside a taller cell), matching the real
    case: a one-line source paragraph translating into more lines than
    it started with, needing genuine room to grow, but only up to the
    cell's own bottom rule -- not past it."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    para = _para((420, 296.6, 581, 305.5), clip=(420, 296.6, 581, 315.9))
    avail = layout.available_rect(page, para, [para])
    assert avail.y1 == pytest.approx(314.9, abs=0.01)  # clip.y1 - 1.0


def test_available_rect_grows_into_free_space_when_no_clip():
    """Without a clip (ordinary flowing prose, not a table cell), growth
    is still bounded only by the page margin or another paragraph below
    -- this must keep working exactly as before the clip-bound fix."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    para = _para((50, 100, 300, 115))
    avail = layout.available_rect(page, para, [para])
    assert avail.y1 == pytest.approx(page.rect.y1 - 18.0)  # default bottom_margin


def test_available_rect_still_bounded_by_paragraph_below_when_present():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    para = _para((50, 100, 300, 115))
    below = _para((50, 200, 300, 215))
    avail = layout.available_rect(page, para, [para, below])
    assert avail.y1 == pytest.approx(199.0)  # below.y0 - 1.0


def test_merge_flowing_paragraphs_noop_on_single_paragraph():
    doc = synth.simple_paragraph_page()
    paras = layout.extract_paragraphs(doc[0])
    merged = layout.merge_flowing_paragraphs(paras, doc[0])
    assert len(merged) == len(paras)


# -- IR conversion -----------------------------------------------------------

def test_page_to_ir_round_trips_paragraph_text():
    doc = synth.simple_paragraph_page()
    page = doc[0]
    paras = layout.extract_paragraphs(page)
    ir_page = layout.page_to_ir(page, paras)
    assert ir_page.number == 0
    assert len(ir_page.paragraphs) == len(paras)
    if paras:
        assert ir_page.paragraphs[0].text == paras[0].text


def test_para_to_ir_preserves_run_style():
    line = synth.make_line([synth.make_span("CONSIDERANDO:", 50.0, 50.0, bold=True)])
    block = synth.make_block([line])
    runs = layout._build_runs([line])
    para = layout.Para(
        runs=runs, text="CONSIDERANDO:", rect=fitz.Rect(block["bbox"]),
        line_rects=[fitz.Rect(line["bbox"])], block_no=0, origin=(50.0, 50.0),
        clip=None, hang_x0=None, align="left", leading=13.0, size=11.0,
        font="Helvetica", color=(0.0, 0.0, 0.0), page=0, indent=0.0,
    )
    ir_para = layout.para_to_ir(para)
    assert ir_para.runs[0].bold is True
    assert ir_para.runs[0].text == "CONSIDERANDO:"
