"""Draw a translated paragraph back onto the page.

What this does differently from a naive per-line renderer
-------------------------------------------------------------
Drawing every unit left-aligned, in one base-14 face, at a size chosen by
shrinking that unit alone until it fits its own box produces a visible
defect whenever a single source LINE is treated as its own unit: adjacent
lines of the same paragraph end up at different sizes (a "first line big,
rest small" effect), and justified source text comes out ragged.

This renderer:
  * keeps styled runs, so a bold lead-in label stays bold
  * reproduces the source alignment, including real justification (extra
    space distributed between words, not appended at the end of the line)
  * uses the paragraph's measured leading rather than a hardcoded ratio
  * scales the WHOLE paragraph uniformly, and only after first trying to
    use genuinely free space below it

Why a context object, not module globals
-------------------------------------------
An earlier version kept the default scan-font family and the font
measurement cache as module-level globals, mutated via a
`set_default_family()` function that also cleared the cache as a side
effect. That makes correctness depend on call order (any code running
after `set_default_family()` for a different document sees the new
default) and is a data race if two documents are ever rendered
concurrently in the same process. `RenderContext` bundles the
`FontResolver`, the default family, and the measurement cache as instance
state instead, so two documents rendered with two different contexts
cannot interfere with each other regardless of ordering or concurrency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz

from palimpsest.pdf.fontmap import FontResolver, base14

# The bullet or enumerator at the head of a list item, captured so it can
# be drawn at the margin while the body hangs at its own indent.
_LEADING_MARKER_RE = re.compile(r"^\s*([•●○◦▪§·]|[a-zA-Z]\)|\d{1,2}[.)])\s+")

MIN_SCALE = 0.72  # below this, shrinking is more disfiguring than reflowing
JUSTIFY_MAX_STRETCH = 2.6  # give up on justifying a line rather than tear it apart

# Face used when the source names no real typeface -- i.e. an OCR text
# layer, where every span claims to be a placeholder font. Overridable per
# RenderContext (and per document via config `[fonts].scan_default`).
DEFAULT_SCAN_FAMILY = "Calibri"


@dataclass
class RenderContext:
    """Everything `draw_paragraph` needs that isn't specific to one
    paragraph: which fonts to use and how aggressively to scale/justify.
    One instance per document (or per concurrent render) keeps state from
    leaking across documents -- see the module docstring."""

    font_resolver: FontResolver
    default_scan_family: str = DEFAULT_SCAN_FAMILY
    min_scale: float = MIN_SCALE
    justify_max_stretch: float = JUSTIFY_MAX_STRETCH

    _font_cache: dict = field(default_factory=dict, init=False, repr=False)

    def font_for(self, style: tuple) -> fitz.Font:
        """Measurement font. Keyed on the full style so the metrics used
        for wrapping are those of the face actually drawn -- measuring in
        regular and drawing in bold would make every bold line overrun
        its box."""
        fontname, _size, bold, ital, _color = style
        key = (fontname, bold, ital, self.default_scan_family)
        if key not in self._font_cache:
            self._font_cache[key] = self.font_resolver.font_object(
                fontname, bold=bold, italic=ital, default_family=self.default_scan_family
            )
        return self._font_cache[key]

    def measure(self, word: str, style: tuple, size: float) -> float:
        return self.font_for(style).text_length(word, fontsize=size)


def _tokenise(segments) -> list[tuple[str, tuple]]:
    """[(text, style)] -> [(word, style)], preserving style across word splits."""
    words = []
    for text, style in segments:
        for w in text.split():
            words.append((w, style))
    return words


def _wrap(ctx: RenderContext, words, size: float, max_width: float, first_indent: float = 0.0):
    """Greedy wrap. Returns list of lines; each line is a list of (word, style)."""
    lines, cur, cur_w = [], [], 0.0
    space_cache: dict = {}

    def space_w(style):
        if style not in space_cache:
            space_cache[style] = ctx.measure(" ", style, size)
        return space_cache[style]

    avail = max_width - first_indent
    for word, style in words:
        w = ctx.measure(word, style, size)
        add = w if not cur else w + space_w(style)
        if cur and cur_w + add > avail:
            lines.append(cur)
            cur, cur_w = [(word, style)], w
            avail = max_width
        else:
            cur.append((word, style))
            cur_w += add
    if cur:
        lines.append(cur)
    return lines or [[]]


def _line_natural_width(ctx: RenderContext, line, size: float) -> float:
    if not line:
        return 0.0
    total = sum(ctx.measure(w, s, size) for w, s in line)
    total += sum(ctx.measure(" ", s, size) for _, s in line[1:])
    return total


def fit_paragraph(
    ctx: RenderContext, segments, size, max_width, max_height, leading, first_indent=0.0
):
    """Choose the largest size <= `size` whose wrap fits `max_height`.

    Returns (size, leading, lines). Scaling stops at `ctx.min_scale`;
    beyond that the text is left slightly over-long rather than rendered
    at an obviously wrong size, and the caller's QA pass will flag it.
    """
    words = _tokenise(segments)
    if not words:
        return size, leading, [[]]
    s = size
    lead = leading
    floor = size * ctx.min_scale
    while True:
        lines = _wrap(ctx, words, s, max_width, first_indent)
        height = (len(lines) - 1) * lead + s
        if height <= max_height or s <= floor:
            return s, lead, lines
        s = max(floor, s - 0.25)
        lead = leading * (s / size)


def draw_paragraph(
    ctx: RenderContext, page: fitz.Page, para, segments, rect, align=None, debug_boxes=False
):
    """Render `segments` into `rect`, honouring the paragraph's original
    alignment, leading and first baseline. Returns a dict of layout facts
    for QA."""
    align = align or para.align
    size = para.size
    leading = para.leading or size * 1.18

    # A bulleted item is drawn as a marker sitting at the left margin plus
    # a text column starting at the source's hanging indent, so wrapped
    # lines line up under the text rather than tucking back under the
    # bullet.
    marker = None
    marker_style = None
    if getattr(para, "hang_x0", None) and segments:
        head_text, head_style = segments[0]
        m = _LEADING_MARKER_RE.match(head_text)
        if m and para.hang_x0 > rect.x0 + 1:
            marker = m.group(1)
            marker_style = head_style
            rest = head_text[m.end():]
            segments = ([(rest, head_style)] if rest.strip() else []) + list(segments[1:])
            rect = fitz.Rect(max(rect.x0, para.hang_x0), rect.y0, rect.x1, rect.y1)

    max_width = max(12.0, rect.width)
    # The first baseline sits `origin.y` below the top; the space
    # actually usable for wrapped lines runs from there to the bottom of
    # `rect`.
    first_baseline = para.origin[1]
    max_height = max(size, rect.y1 - first_baseline + size)

    fitted, lead, lines = fit_paragraph(ctx, segments, size, max_width, max_height, leading)

    if marker is not None:
        alias = ctx.font_resolver.alias_for(
            page, marker_style[0], bold=marker_style[2], italic=marker_style[3],
            default_family=ctx.default_scan_family,
        )
        try:
            page.insert_text(
                (para.rect.x0, first_baseline), marker, fontname=alias,
                fontsize=fitted, color=marker_style[4], overlay=True,
            )
        except Exception:
            page.insert_text(
                (para.rect.x0, first_baseline), marker,
                fontname=base14(marker_style[2], marker_style[3]),
                fontsize=fitted, color=marker_style[4], overlay=True,
            )

    y = first_baseline
    drawn = 0
    for i, line in enumerate(lines):
        if not line:
            y += lead
            continue
        natural = _line_natural_width(ctx, line, fitted)
        is_last = i == len(lines) - 1
        gaps = len(line) - 1
        extra_per_gap = 0.0
        x = rect.x0
        if align == "justify" and not is_last and gaps > 0:
            extra = max_width - natural
            if 0 < extra:
                per = extra / gaps
                # Do not stretch a nearly-empty line into a sparse mess.
                if per <= ctx.justify_max_stretch * ctx.measure(" ", line[0][1], fitted):
                    extra_per_gap = per
        elif align == "center":
            x = rect.x0 + (max_width - natural) / 2.0
        elif align == "right":
            x = rect.x1 - natural

        for j, (word, style) in enumerate(line):
            if j:
                x += ctx.measure(" ", style, fitted) + extra_per_gap
            alias = ctx.font_resolver.alias_for(
                page, style[0], bold=style[2], italic=style[3],
                default_family=ctx.default_scan_family,
            )
            color = style[4]
            try:
                page.insert_text(
                    (x, y), word, fontname=alias, fontsize=fitted, color=color, overlay=True
                )
            except Exception:
                page.insert_text(
                    (x, y), word, fontname=base14(style[2], style[3]),
                    fontsize=fitted, color=color, overlay=True,
                )
            x += ctx.measure(word, style, fitted)
        drawn += 1
        y += lead

    if debug_boxes:
        page.draw_rect(rect, color=(1, 0, 0), width=0.4)

    return {
        "lines": len(lines),
        "size": fitted,
        "orig_size": size,
        "scaled": fitted < size - 0.01,
        "bottom": y - lead,
        "overflow": (y - lead) > rect.y1 + 1.0,
        "align": align,
    }
