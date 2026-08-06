"""Extract translatable paragraphs from a PDF page, preserving the layout
facts needed to redraw them faithfully.

What this keeps that a naive extraction discards
---------------------------------------------------
A flat "unit" carrying a single font/size taken from the paragraph's
dominant span throws away everything else that makes a paragraph read
correctly once redrawn: bold/italic runs inside the paragraph, the
paragraph's alignment, its real line spacing. This module keeps:

  * `runs`   -- styled fragments, so a bold lead-in label (`CONSIDERANDO:`)
                stays bold when the rest of the sentence is not
  * `align`  -- inferred from the geometry of the source lines, so
                justified text stays justified
  * `leading`-- the measured baseline-to-baseline distance, so vertical
                rhythm is reproduced instead of being hardcoded to a fixed
                multiple of the type size
  * `origin` -- the first baseline, and the block's true width, so
                nothing has to be guessed from a hardcoded page margin
                (fixed-width assumptions break on any page that isn't
                exactly US Letter)
"""

from __future__ import annotations

import re
import statistics

import fitz

from palimpsest.core import ir
from palimpsest.text import ordinals

# Private-Use-Area codepoints are decorative icon-font mappings, never content.
_PUA_RE = re.compile(r"[-]")
_ZW_RE = re.compile("[​‌‍﻿]")

NUM_ONLY_RE = re.compile(r"^[\d.,()%\-\s–—°ºª/:$]*$")
BULLET_CHARS = {"•", "●", "○", "◦", "▪", "§", "·", "-", "—", "–"}

# A real single-line span's declared size and its own measured bbox height
# move together -- for genuine text, size/height sits well under 1. On a
# scanned page, OCR occasionally reads a few characters of noise out of a
# large decorative graphic (a seal, a QR code, a signature block) and
# reports a huge inferred size for it, because that size comes from the
# apparent glyph height *within the graphic region it was misread from*,
# not from any real font metric. The bbox stays small (a handful of
# points -- the actual "glyphs" are tiny artifacts), so the ratio spikes
# far past anything real text produces. Rejecting on that ratio, not on
# the size or the recognized text alone, is what catches this: the size
# alone looks like a plausible large heading, and the text alone can look
# like plausible short noise either way -- it's the two disagreeing that
# gives it away. See docs/design/limitations.md for the general
# "OCR reads noise out of decorative graphics" limitation this sharpens.
_MAX_SIZE_TO_HEIGHT_RATIO = 1.5

# fitz span flag bits
FLAG_ITALIC = 1 << 1
FLAG_BOLD = 1 << 4


def clean(s: str | None) -> str:
    return _ZW_RE.sub("", _PUA_RE.sub("", s or ""))


def span_color(span: dict) -> tuple[float, float, float]:
    c = span.get("color", 0)
    return (((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0)


def span_is_bold(span: dict) -> bool:
    if span.get("flags", 0) & FLAG_BOLD:
        return True
    name = span.get("font", "")
    return "Bold" in name or "bold" in name or "Black" in name or "Heavy" in name


def span_is_italic(span: dict) -> bool:
    if span.get("flags", 0) & FLAG_ITALIC:
        return True
    name = span.get("font", "")
    return "Italic" in name or "Oblique" in name


class Para:
    __slots__ = (
        "runs", "rect", "origin", "align", "leading", "size", "font",
        "color", "page", "indent", "line_rects", "text", "block_no", "clip",
        "hang_x0", "starts_item",
    )

    runs: list[dict]
    rect: fitz.Rect
    origin: tuple[float, float]
    align: str
    leading: float | None
    size: float
    font: str
    color: tuple[float, float, float]
    page: int
    indent: float
    line_rects: list[fitz.Rect]
    text: str
    block_no: int
    clip: fitz.Rect | None
    hang_x0: float | None
    starts_item: bool

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __repr__(self):
        return f"<Para p{self.page} {self.align} size={self.size:.1f} {self.text[:48]!r}>"


def _line_text(line: dict) -> str:
    return clean("".join(s["text"] for s in line["spans"]))


def _dominant_span(spans: list[dict]) -> dict:
    best, best_len = None, -1
    for s in spans:
        n = len(clean(s["text"]).strip())
        if n > best_len:
            best, best_len = s, n
    return best or spans[0]


def _detect_align(line_rects: list[fitz.Rect], block_rect: fitz.Rect, tol: float = 2.0) -> str:
    """Infer paragraph alignment from the geometry of its lines.

    A single-line paragraph carries no wrap evidence, so it is reported
    as 'left' unless it is visibly centred within the block.
    """
    if len(line_rects) == 1:
        r = line_rects[0]
        left_gap = r.x0 - block_rect.x0
        right_gap = block_rect.x1 - r.x1
        if left_gap > 6 and abs(left_gap - right_gap) < max(tol, 0.18 * max(left_gap, right_gap)):
            return "center"
        if left_gap > 6 and right_gap <= tol:
            return "right"
        return "left"

    lefts = [r.x0 for r in line_rects]
    rights = [r.x1 for r in line_rects]
    # The last line of a justified paragraph is short by definition; judge
    # right-edge agreement on the lines that actually wrapped.
    body_rights = rights[:-1] if len(rights) > 2 else rights
    left_spread = max(lefts) - min(lefts)
    right_spread = max(body_rights) - min(body_rights)

    if left_spread <= tol and right_spread <= tol:
        return "justify"
    if left_spread <= tol:
        return "left"
    if right_spread <= tol and left_spread > tol:
        return "right"
    centers = [(r.x0 + r.x1) / 2 for r in line_rects]
    if max(centers) - min(centers) <= tol * 1.5:
        return "center"
    return "left"


def _measure_leading(lines: list[dict]) -> float | None:
    """Baseline-to-baseline distance, taken as the median of observed gaps."""
    if len(lines) < 2:
        return None
    ys = [line["spans"][0]["origin"][1] for line in lines if line["spans"]]
    gaps = [b - a for a, b in zip(ys, ys[1:], strict=False) if 0 < (b - a) < 200]
    if not gaps:
        return None
    return statistics.median(gaps)


# An OCR text layer reports its own bbox-derived size per WORD, not per line --
# on a single visual heading, OCR commonly yields several slightly different
# sizes for words on the same physical line (e.g. 10.80 / 10.89 / 11.19).
# Rounded to 1 decimal these land in different buckets, so without tolerance
# every OCR'd heading of more than one word fragments into spurious same-line
# "runs". That fragmentation is dangerous downstream: a differently-styled
# leading run reads as a label (like "CONSIDERANDO:") to heuristics that
# split labels out for separate translation, which can send an isolated
# fragment of a company name to the translation backend on its own -- this is
# the documented root cause of a real corpus bug where "GRUPO" (part of a
# longer company name) was translated in isolation into "CLUSTER". Sizes
# within this tolerance of the run's OPENING span are treated as the same
# style; the tolerance is compared against the run's first span (not the
# previous one) so it cannot drift upward one small step at a time.
_SIZE_JITTER_TOL = 0.75


def _build_runs(lines: list[dict], size_jitter_tolerance: float = _SIZE_JITTER_TOL) -> list[dict]:
    """Flatten a paragraph's lines into styled runs, merging adjacent
    spans that share a style so the renderer does not fragment words
    needlessly.

    Word-joining across a line break inserts a single space: PDF lines
    carry no trailing space of their own, and concatenating them raw
    would weld the last word of one line onto the first of the next.
    """
    runs: list[dict] = []
    run_ref_size: list[float] = []  # parallel to `runs`: the opening span's exact size
    for li, line in enumerate(lines):
        if li > 0 and runs:
            runs[-1]["text"] += " "
        for sp in line["spans"]:
            t = clean(sp["text"])
            if not t:
                continue
            size = sp.get("size", 10)
            key = (sp.get("font", ""), span_is_bold(sp), span_is_italic(sp), span_color(sp))
            joined = False
            if runs:
                last = runs[-1]
                last_key = (last["style"][0], last["style"][2], last["style"][3], last["style"][4])
                if key == last_key and abs(size - run_ref_size[-1]) <= size_jitter_tolerance:
                    last["text"] += t
                    joined = True
            if not joined:
                style = (
                    sp.get("font", ""), round(size, 1),
                    span_is_bold(sp), span_is_italic(sp), span_color(sp),
                )
                runs.append({"text": t, "style": style})
                run_ref_size.append(size)
    for r in runs:
        r["text"] = re.sub(r"\s+", " ", r["text"])
    # Drop runs that became empty after whitespace collapsing
    runs = [r for r in runs if r["text"].strip() or len(runs) == 1]
    return runs


# A line opening with one of these starts a new logical paragraph even when it
# sits at normal body spacing -- otherwise 'a) ... b) ...' list items get welded
# into a single flowing sentence.
LIST_MARKER_RE = re.compile(
    r"^\s*(?:[a-zA-Z]\)|\(?[ivxIVX]{1,4}\)|\d{1,2}[.)]|[•●○◦▪§·]|[-–—]\s)\s*"
)

# A fragment that is nothing but an enumerator. Such a fragment is a list
# marker sitting in its own little column, not a table column of its own.
STANDALONE_MARKER_RE = re.compile(
    r"^\s*(?:[a-zA-Z]\)|\(?[ivxIVX]{1,5}\)|\d{1,2}[.)]|[•●○◦▪§·])\s*$"
)


def _visual_rows(lines: list[dict], overlap_frac: float = 0.5) -> list[dict]:
    """Group lines that share a horizontal band (i.e. sit on the same row)."""
    rows: list[dict] = []
    for line in sorted(lines, key=lambda line: line["bbox"][1]):
        y0, y1 = line["bbox"][1], line["bbox"][3]
        for row in rows:
            ov = min(y1, row["y1"]) - max(y0, row["y0"])
            if ov > overlap_frac * min(y1 - y0, row["y1"] - row["y0"] or 1):
                row["lines"].append(line)
                row["y0"] = min(row["y0"], y0)
                row["y1"] = max(row["y1"], y1)
                break
        else:
            rows.append({"y0": y0, "y1": y1, "lines": [line]})
    return rows


def merge_row_fragments(lines: list[dict], min_col_gap: float = 9.0) -> list[dict]:
    """Rejoin pieces of a single physical line that the extractor split.

    OCR routinely emits e.g. `144` and `months.` as two separate lines
    sitting on the same baseline a couple of points apart. Left alone
    they look exactly like two table columns to `column_bands`, and get
    translated and redrawn as two independent paragraphs.

    Fragments on the same row are merged when the horizontal gap between
    them is smaller than a real column gutter; anything wider is left for
    column detection to handle.
    """
    out = []
    for row in _visual_rows(lines):
        cells = sorted(row["lines"], key=lambda line: line["bbox"][0])
        cur = [cells[0]]
        for prev, nxt in zip(cells, cells[1:], strict=False):
            size = max(_dominant_span(prev["spans"]).get("size", 10), 1.0)
            gap = nxt["bbox"][0] - prev["bbox"][2]
            # A bullet glyph is always its own fragment and sits a wide,
            # deliberate gutter away from the text it introduces. Bind the
            # two together regardless of that gap: otherwise the bullet
            # is dropped as non-text, the item bodies merge into each
            # other, and the page ends up with a column of orphaned
            # bullets beside a run-on paragraph.
            prev_txt = _line_text(prev).strip()
            is_bullet = prev_txt in BULLET_CHARS or bool(STANDALONE_MARKER_RE.match(prev_txt))
            if gap < max(min_col_gap, size * 1.1) or (is_bullet and gap < 60.0):
                cur.append(nxt)
            else:
                out.append(_join_lines(cur))
                cur = [nxt]
        out.append(_join_lines(cur))
    return out


def _join_lines(parts: list[dict]) -> dict:
    """Combine same-row line fragments into one synthetic line."""
    if len(parts) == 1:
        return parts[0]
    ordered = sorted(parts, key=lambda line: line["bbox"][0])
    spans = []
    for i, line in enumerate(ordered):
        if i:
            pad = dict(ordered[i - 1]["spans"][-1])
            pad["text"] = " "
            spans.append(pad)
        spans.extend(line["spans"])
    joined = {
        "bbox": (
            min(line["bbox"][0] for line in ordered),
            min(line["bbox"][1] for line in ordered),
            max(line["bbox"][2] for line in ordered),
            max(line["bbox"][3] for line in ordered),
        ),
        "spans": spans,
    }
    # Remember where the text after a bullet begins, so the item can be
    # redrawn with the same hanging indent instead of wrapping back under
    # its bullet.
    head = _line_text(ordered[0]).strip()
    if len(ordered) > 1 and (head in BULLET_CHARS or STANDALONE_MARKER_RE.match(head)):
        joined["hang_x0"] = ordered[1]["bbox"][0]
    return joined


def column_bands(lines: list[dict], overlap_frac: float = 0.35):
    """Split a block's lines into columns, derived from the block's own geometry.

    Why not a table-detection API: on real-world scanned documents, such
    detectors can slice a tall cell into one sub-cell per text line (a
    multi-line project description coming back as five separate 12pt-high
    cells), which shatters a paragraph into per-line fragments -- exactly
    the pathology this module exists to avoid. The block's own line
    geometry is a far more reliable signal.

    Columns are only inferred when some visual row genuinely holds more
    than one line; a normal flowing paragraph always yields a single
    band, so its lines stay together.
    """
    rows = _visual_rows(lines)
    if not any(len(r["lines"]) > 1 for r in rows):
        return [(None, list(lines))]

    bands: list[dict] = []
    for line in sorted(lines, key=lambda line: line["bbox"][0]):
        x0, x1 = line["bbox"][0], line["bbox"][2]
        for b in bands:
            ov = min(x1, b["x1"]) - max(x0, b["x0"])
            if ov > overlap_frac * min(x1 - x0, b["x1"] - b["x0"] or 1):
                b["x0"] = min(b["x0"], x0)
                b["x1"] = max(b["x1"], x1)
                b["lines"].append(line)
                break
        else:
            bands.append({"x0": x0, "x1": x1, "lines": [line]})
    return [((b["x0"], b["x1"]), b["lines"]) for b in bands]


def _group_lines_into_paragraphs(block: dict, lines: list[dict] | None = None) -> list[list[dict]]:
    """Split a text block into paragraphs on indent / spacing / style breaks.

    PDF text blocks frequently contain several visual paragraphs.
    Splitting on a larger-than-usual vertical gap, a type-size change, or
    a list marker keeps a heading from being welded onto the body text
    that follows it.
    """
    if lines is None:
        lines = [
            ln for ln in block.get("lines", [])
            if ln.get("spans") and _line_text(ln).strip()
        ]
    if not lines:
        return []
    lines = sorted(lines, key=lambda line: (round(line["bbox"][1], 1), line["bbox"][0]))
    if len(lines) == 1:
        return [lines]

    gaps = [b["bbox"][1] - a["bbox"][3] for a, b in zip(lines, lines[1:], strict=False)]
    typical = statistics.median([g for g in gaps if g > -5] or [0])
    sizes = [_dominant_span(ln["spans"]).get("size", 10) for ln in lines]
    typ_size = statistics.median(sizes)
    margin_x0 = min(ln["bbox"][0] for ln in lines)

    groups = [[lines[0]]]
    for i, (a, b) in enumerate(zip(lines, lines[1:], strict=False)):
        gap = gaps[i]
        size_a = _dominant_span(a["spans"]).get("size", 10)
        size_b = _dominant_span(b["spans"]).get("size", 10)
        text_b = _line_text(b)
        new_para = False
        # A clearly larger vertical gap than the block's norm
        if gap > max(typical + 0.6 * typ_size, typical * 1.8 + 1.0):
            new_para = True
        # A change of type size is a structural break (heading vs body)
        if abs(size_a - size_b) > 0.6:
            new_para = True
        # An enumerated item always starts its own paragraph
        if LIST_MARKER_RE.match(text_b):
            new_para = True
        # A spelled-out legal ordinal ('DECIMO SEGUNDO.') always opens a
        # new clause. Needed because these headings are frequently set in
        # the same weight and size as body text (no bold, no size jump),
        # so nothing else here would catch them -- without this, a clause
        # heading gets welded onto whatever line preceded it, most
        # damagingly a wrapped list-item continuation, producing one
        # run-on paragraph that mixes a numbered list body with the next
        # clause's heading and text.
        if ordinals.HEADING_RE.match(text_b):
            new_para = True
        # A line returning to the block's left margin closes an indented
        # LIST ITEM's hanging body, even when nothing else here flags it
        # -- catches clause headings that are neither bold/larger nor a
        # recognised ordinal. Deliberately scoped to "the group currently
        # open was opened by a list marker": a plain document that
        # indents a paragraph's FIRST line and sets continuations flush
        # left (an unrelated, common typographic convention) must NOT
        # have every one of those normal continuation lines treated as
        # starting a new paragraph.
        group_opener = _line_text(groups[-1][0])
        in_list_item = bool(LIST_MARKER_RE.match(group_opener))
        if (
            in_list_item
            and b["bbox"][0] <= margin_x0 + 1.0
            and a["bbox"][0] > margin_x0 + 8.0
        ):
            new_para = True
        if new_para:
            groups.append([b])
        else:
            groups[-1].append(b)
    return groups


def extract_paragraphs(
    page: fitz.Page, min_size: float = 3.0, use_tables: bool = True
) -> list[Para]:
    """Return the page's translatable paragraphs as Para objects.

    When the page contains tables, lines are partitioned by table cell
    first so that no paragraph -- and therefore no translation unit and
    no redraw box -- ever spans a column boundary.
    """
    d = page.get_text("dict")
    paras = []
    for bno, block in enumerate(d.get("blocks", [])):
        if block.get("type") != 0:
            continue

        block_lines = [
            ln for ln in block.get("lines", [])
            if ln.get("spans") and _line_text(ln).strip()
        ]
        if not block_lines:
            continue

        # Rejoin split fragments of single lines, then split into columns
        # so a paragraph can never span a table's column boundary, then
        # group each column into paragraphs.
        if use_tables:
            block_lines = merge_row_fragments(block_lines)
        line_groups = []
        for band, bl in (column_bands(block_lines) if use_tables else [(None, block_lines)]):
            for grp in _group_lines_into_paragraphs(block, bl):
                line_groups.append((band, grp))

        for band, lines in line_groups:
            text = " ".join(_line_text(ln).strip() for ln in lines)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", text):
                continue
            if NUM_ONLY_RE.match(text):
                continue
            if text in BULLET_CHARS:
                continue

            line_rects = [fitz.Rect(ln["bbox"]) for ln in lines]
            rect = fitz.Rect(line_rects[0])
            for r in line_rects[1:]:
                rect |= r
            block_rect = fitz.Rect(block["bbox"])
            # In a multi-column block the column -- not the whole block --
            # is the box the paragraph must live in, for both alignment
            # and wrap width. `None` means the block is a single flowing
            # column.
            clip = fitz.Rect(band[0], block_rect.y0, band[1], block_rect.y1) if band else None
            container = clip if clip is not None else block_rect
            dom = _dominant_span([s for ln in lines for s in ln["spans"]])
            size = dom.get("size", 10.0)
            if size < min_size:
                continue
            if len(lines) == 1 and size > rect.height * _MAX_SIZE_TO_HEIGHT_RATIO:
                continue

            runs = _build_runs(lines)
            if not runs:
                continue

            first_span = lines[0]["spans"][0]
            paras.append(Para(
                runs=runs,
                text=text,
                rect=rect,
                line_rects=line_rects,
                block_no=bno,
                origin=tuple(first_span["origin"]),
                clip=clip,
                hang_x0=lines[0].get("hang_x0"),
                align=_detect_align(line_rects, container),
                leading=_measure_leading(lines) or (size * 1.18),
                size=size,
                font=dom.get("font", "Helvetica"),
                color=span_color(dom),
                page=page.number,
                indent=line_rects[0].x0 - min(r.x0 for r in line_rects),
            ))
    return paras


def merge_flowing_paragraphs(
    paras: list[Para], page: fitz.Page, max_size_delta: float = 0.6
) -> list[Para]:
    """Join paragraphs that a page's block segmentation split mid-sentence.

    An OCR text layer emits one block per physical LINE, so a five-line
    paragraph arrives as five separate blocks. Left unmerged, each line
    is translated in isolation (poor quality, since no line is a whole
    sentence) and redrawn as its own ragged one-liner.

    The reliable continuation signal in a justified or full-measure
    document is that the previous line reaches the right-hand text
    margin. A line that stops short of it ended its paragraph.
    """
    if len(paras) < 2:
        return paras
    right_edge = max(p.rect.x1 for p in paras)
    ordered = sorted(paras, key=lambda p: (round(p.rect.y0, 1), p.rect.x0))

    merged: list[Para] = []
    for para in ordered:
        if not merged:
            merged.append(para)
            continue
        prev = merged[-1]
        gap = para.rect.y0 - prev.rect.y1
        lead = prev.leading or prev.size * 1.18
        # Continuation lines of a bulleted item start at the hanging
        # indent, not at the bullet, so compare against that when one is
        # present.
        prev_text_x0 = prev.hang_x0 if prev.hang_x0 else prev.rect.x0
        same_col = (
            min(abs(para.rect.x0 - prev.rect.x0), abs(para.rect.x0 - prev_text_x0)) < 12.0
            and (para.clip is None) == (prev.clip is None)
        )
        prev_full = prev.rect.x1 >= right_edge - max(14.0, prev.size * 1.6)
        # A short line still continues if it does not close a sentence
        # and the next line opens mid-thought. Inside a narrow table cell
        # nothing ever reaches the page's right margin, so the
        # full-measure test alone would leave e.g. "Term: | 144" and
        # "months." as two separate paragraphs.
        prev_open = not prev.text.rstrip().endswith((".", ":", ";", "!", "?", '"', "”"))
        next_continues = bool(para.text[:1].islower() or para.text[:1].isdigit())
        joinable = (
            same_col
            and (prev_full or (prev_open and next_continues))
            and abs(para.size - prev.size) <= max_size_delta
            and -1.0 <= gap <= lead * 0.85
            and not LIST_MARKER_RE.match(para.text)
            # A bullet sits to the left of this line: it opens a new item.
            and not getattr(para, "starts_item", False)
        )
        if joinable:
            prev.runs = prev.runs + [{"text": " ", "style": prev.runs[-1]["style"]}] + para.runs
            prev.text = (prev.text + " " + para.text).strip()
            prev.line_rects = prev.line_rects + para.line_rects
            prev.rect = prev.rect | para.rect
            if prev.leading is None or len(prev.line_rects) == 2:
                prev.leading = max(gap + prev.size, prev.size * 1.15)
            # A multi-line block that fills the measure is justified in practice.
            if prev.align == "left":
                prev.align = "justify"
        else:
            merged.append(para)

    for p in merged:
        # Collapse the whitespace introduced by joining runs.
        for r in p.runs:
            r["text"] = re.sub(r"\s+", " ", r["text"])
        p.text = re.sub(r"\s+", " ", p.text).strip()
    return merged


def page_obstacle_rects(page: fitz.Page) -> list[fitz.Rect]:
    """Rects on the page that hold content outside the normal text flow
    and must never be drawn over or under: annotations (stamps,
    signature boxes).

    A Stamp annotation's own appearance -- a seal, a digital-signature
    block -- is not visible to `get_text()` at all (annotations render in
    a separate layer on top of page content), so nothing about it shows
    up as a 'paragraph' for `available_rect`'s ordinary
    paragraph-vs-paragraph spacing to avoid. Left unhandled, a
    translation that runs a line or two longer than its source (common
    when translating into English) can wrap down into that space and
    render UNDER the annotation, where it is invisible or only partially
    visible in any viewer.
    """
    rects = []
    try:
        annots = list(page.annots())
    except Exception:
        return rects
    for a in annots:
        r = fitz.Rect(a.rect)
        if not r.is_empty and not r.is_infinite:
            rects.append(r)
    return rects


def available_rect(
    page: fitz.Page, para: Para, paras: list[Para], bottom_margin: float = 18.0,
    cell_pad: float = 2.5, obstacles=(),
) -> fitz.Rect:
    """The box this paragraph may occupy: its own width, grown downward
    into genuinely free space so a slightly longer translation reflows
    instead of being shrunk.

    A paragraph inside a table cell is confined to that cell (minus a
    small padding) in BOTH axes -- it must never spill into the
    neighbouring column or push through the cell's bottom rule.

    `obstacles` (see `page_obstacle_rects`) are treated exactly like
    another paragraph below: growth stops before reaching them, never on
    top of them.
    """
    r = fitz.Rect(para.rect)
    limit = page.rect.y1 - bottom_margin
    if para.clip is not None:
        # Confine to the column so text can never bleed into the next one.
        col = fitz.Rect(para.clip)
        r.x0 = max(r.x0, col.x0)
        r.x1 = min(max(r.x1, r.x0 + 10.0), col.x1 + cell_pad)
        # The cell's own bottom rule bounds downward growth too -- without
        # this, a cell with no extracted paragraph below it (common on a
        # scanned table row where the neighbouring cell's content didn't
        # qualify as translatable, e.g. it was a bare "N/D") had nothing
        # to stop it growing, and a translation running a line longer
        # than its source bled straight through into the next row.
        limit = min(limit, col.y1 - 1.0)

    for other in paras:
        if other is para:
            continue
        o = other.rect
        # only things below us that horizontally overlap our column
        if o.y0 < r.y1 - 0.5:
            continue
        if o.x1 <= r.x0 + 1 or o.x0 >= r.x1 - 1:
            continue
        limit = min(limit, o.y0 - 1.0)
    for o in obstacles:
        if o.y0 < r.y1 - 0.5:
            continue
        if o.x1 <= r.x0 + 1 or o.x0 >= r.x1 - 1:
            continue
        limit = min(limit, o.y0 - 1.0)
    # Never shrink below the paragraph's own height.
    r.y1 = max(r.y1, min(limit, page.rect.y1 - bottom_margin))
    return r


# ---------------------------------------------------------------------------
# Serialization to the shared IR (see core.ir)
# ---------------------------------------------------------------------------


def _run_to_ir(run: dict) -> ir.Run:
    font, size, bold, italic, color = run["style"]
    return ir.Run(text=run["text"], font=font, size=size, bold=bold, italic=italic, color=color)


def _rect_to_ir(r: fitz.Rect | None) -> ir.Rect | None:
    if r is None:
        return None
    return ir.Rect(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)


def para_to_ir(para: Para) -> ir.Paragraph:
    return ir.Paragraph(
        text=para.text,
        runs=tuple(_run_to_ir(r) for r in para.runs),
        rect=_rect_to_ir(para.rect),
        origin=tuple(para.origin),
        align=para.align,
        leading=para.leading,
        size=para.size,
        font=para.font,
        color=para.color,
        indent=para.indent or 0.0,
        hang_x0=para.hang_x0,
        starts_item=bool(getattr(para, "starts_item", False)),
        clip=_rect_to_ir(para.clip),
    )


def page_to_ir(page: fitz.Page, paras: list[Para]) -> ir.Page:
    return ir.Page(
        number=page.number,
        width=page.rect.width,
        height=page.rect.height,
        paragraphs=tuple(para_to_ir(p) for p in paras),
    )
