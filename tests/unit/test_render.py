import fitz

from palimpsest.pdf.fontmap import FontResolver
from palimpsest.pdf.layout import Para
from palimpsest.pdf.render import RenderContext, draw_paragraph, fit_paragraph


def _ctx() -> RenderContext:
    # An empty-index FontResolver resolves everything to base-14, which
    # needs no real font file -- exactly what makes this reproducible
    # across machines/CI without bundled fonts.
    return RenderContext(font_resolver=FontResolver(use_bundled_fallback=False))


STYLE = ("helv", 12.0, False, False, (0.0, 0.0, 0.0), False, None)
BOLD_STYLE = ("helv", 12.0, True, False, (0.0, 0.0, 0.0), False, None)
UNDERLINE_STYLE = ("helv", 12.0, False, False, (0.0, 0.0, 0.0), True, None)
HIGHLIGHT_STYLE = ("helv", 12.0, False, False, (0.0, 0.0, 0.0), False, (1.0, 0.9, 0.5))


def test_fit_paragraph_returns_original_size_when_it_fits():
    ctx = _ctx()
    segments = [("short text", STYLE)]
    size, leading, lines = fit_paragraph(
        ctx, segments, size=12.0, max_width=300, max_height=100, leading=14.0
    )
    assert size == 12.0
    assert leading == 14.0
    assert len(lines) == 1


def test_fit_paragraph_shrinks_when_too_tall_for_box():
    ctx = _ctx()
    long_text = " ".join(["palabra"] * 60)
    segments = [(long_text, STYLE)]
    size, _leading, _lines = fit_paragraph(
        ctx, segments, size=12.0, max_width=100, max_height=20, leading=14.0
    )
    assert size < 12.0
    assert size >= 12.0 * ctx.min_scale - 1e-6


def test_fit_paragraph_never_shrinks_below_min_scale_floor():
    ctx = _ctx()
    long_text = " ".join(["palabraextensa"] * 200)
    segments = [(long_text, STYLE)]
    size, _leading, _lines = fit_paragraph(
        ctx, segments, size=12.0, max_width=50, max_height=10, leading=14.0
    )
    floor = 12.0 * ctx.min_scale
    assert size >= floor - 1e-6


def test_fit_paragraph_empty_segments_returns_input_size():
    ctx = _ctx()
    size, leading, lines = fit_paragraph(
        ctx, [], size=12.0, max_width=300, max_height=100, leading=14.0
    )
    assert size == 12.0
    assert leading == 14.0
    assert lines == [[]]


def _make_para(text: str, align: str = "left") -> Para:
    rect = fitz.Rect(20, 30, 300, 60)
    return Para(
        runs=[{"text": text, "style": STYLE}], text=text, rect=rect,
        line_rects=[rect], block_no=0, origin=(20.0, 42.0), clip=None,
        hang_x0=None, align=align, leading=14.0, size=12.0, font="helv",
        color=(0.0, 0.0, 0.0), page=0, indent=0.0,
    )


def test_draw_paragraph_returns_layout_facts():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Texto traducido de prueba")
    segments = [("Texto traducido de prueba", STYLE)]
    facts = draw_paragraph(ctx, page, para, segments, para.rect)
    assert facts["lines"] >= 1
    assert facts["align"] == "left"
    assert not facts["overflow"]


def test_draw_paragraph_actually_draws_text_on_the_page():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Approved translation text")
    segments = [("Approved translation text", STYLE)]
    draw_paragraph(ctx, page, para, segments, para.rect)
    assert "Approved" in page.get_text()


def test_draw_paragraph_draws_highlight_rect_behind_marked_words():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Marked word")
    segments = [("Marked word", HIGHLIGHT_STYLE)]
    draw_paragraph(ctx, page, para, segments, para.rect)
    fills = [d["fill"] for d in page.get_drawings() if d.get("fill")]
    assert fills, "expected a filled rect for a word with a highlight style"
    assert all(abs(c - e) < 1e-3 for c, e in zip(fills[0], HIGHLIGHT_STYLE[6], strict=True))


def test_draw_paragraph_draws_no_highlight_when_style_has_none():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Plain word")
    segments = [("Plain word", STYLE)]
    draw_paragraph(ctx, page, para, segments, para.rect)
    fills = [d["fill"] for d in page.get_drawings() if d.get("fill")]
    assert not fills


def test_draw_paragraph_draws_underline_stroke_for_marked_words():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Underlined word")
    segments = [("Underlined word", UNDERLINE_STYLE)]
    draw_paragraph(ctx, page, para, segments, para.rect)
    strokes = [d for d in page.get_drawings() if d.get("items") and not d.get("fill")]
    assert any(item[0] == "l" for d in strokes for item in d["items"])


def test_draw_paragraph_justify_distributes_space_between_words():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    text = "one two three four five six seven eight nine ten eleven twelve"
    para = _make_para(text, align="justify")
    segments = [(text, STYLE)]
    facts = draw_paragraph(ctx, page, para, segments, para.rect)
    assert facts["align"] == "justify"
    assert facts["lines"] >= 2


def test_draw_paragraph_debug_boxes_draws_a_rect():
    ctx = _ctx()
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    para = _make_para("Texto")
    segments = [("Texto", STYLE)]
    drawings_before = len(page.get_drawings())
    draw_paragraph(ctx, page, para, segments, para.rect, debug_boxes=True)
    assert len(page.get_drawings()) > drawings_before


def test_render_context_font_cache_is_instance_scoped():
    """The bug this replaces: a module-global font cache mutated by a
    set_default_family() side effect meant two documents rendered in the
    same process could interfere with each other. Two independently
    constructed contexts must not share cache state."""
    ctx1 = _ctx()
    ctx2 = _ctx()
    ctx1.font_for(STYLE)
    assert ctx1._font_cache is not ctx2._font_cache
    assert len(ctx1._font_cache) == 1
    assert len(ctx2._font_cache) == 0


def test_render_context_different_default_scan_family_do_not_collide():
    resolver = FontResolver(use_bundled_fallback=False)
    ctx_a = RenderContext(font_resolver=resolver, default_scan_family="Calibri")
    ctx_b = RenderContext(font_resolver=resolver, default_scan_family="Georgia")
    ctx_a.font_for(STYLE)
    ctx_b.font_for(STYLE)
    # Distinct cache dicts even when sharing one FontResolver.
    assert ctx_a._font_cache is not ctx_b._font_cache
