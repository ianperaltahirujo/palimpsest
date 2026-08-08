"""Serializable intermediate representation for extracted page layout.

Why this exists
----------------
Layout extraction (`pdf.layout`) and rendering (`pdf.render`) both operate
on live PyMuPDF `Page` objects, so nothing between "extract" and "draw" is
inspectable or testable without a real PDF and a real render. That has
three concrete costs:

1. A layout regression can only be caught by rendering a page and diffing
   images, which is slow and requires a real fixture document.
2. Reproducing a reported layout bug means shipping the (often
   confidential) source PDF that triggered it.
3. A translation backend that could use whole-page context (surrounding
   paragraphs, not just the one string being translated) has no way to
   see it, because nothing captures "the page" as data.

This module is a thin serialization boundary, not a document model: a
`Document` here is a snapshot of what `pdf.layout.extract_paragraphs`
found, expressible as JSON, diffable as a golden file, and convertible
back and forth without touching PyMuPDF at all.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Align = Literal["left", "right", "center", "justify"]


@dataclass(frozen=True)
class Run:
    """One styled fragment of a paragraph's text."""

    text: str
    font: str
    size: float
    bold: bool
    italic: bool
    color: tuple[float, float, float]
    underline: bool = False
    highlight: tuple[float, float, float] | None = None
    """Both default False/None because source-PDF extraction never
    produces either -- they only ever come from the web UI's edit mode
    (see `pdf.reflow`), which is also the only place that draws them."""


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class Paragraph:
    text: str
    runs: tuple[Run, ...]
    rect: Rect
    origin: tuple[float, float]
    align: Align
    leading: float
    size: float
    font: str
    color: tuple[float, float, float]
    indent: float = 0.0
    hang_x0: float | None = None
    starts_item: bool = False
    # The column band this paragraph belongs to, if the source block was
    # split into columns -- (x0, x1) in page coordinates, or None for a
    # single flowing column.
    clip: Rect | None = None


@dataclass(frozen=True)
class Page:
    number: int
    width: float
    height: float
    paragraphs: tuple[Paragraph, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Document:
    source: str
    """Identifying label for the source, e.g. a filename. Deliberately not
    validated or required to be a real path -- IR dumps are meant to be
    shareable without necessarily shipping the source file itself."""

    pages: tuple[Page, ...] = field(default_factory=tuple)


def _tuple_hook(obj: Any) -> Any:
    if isinstance(obj, dict) and set(obj) == {"x0", "y0", "x1", "y1"}:
        return Rect(**obj)
    return obj


def to_dict(doc: Document) -> dict[str, Any]:
    return asdict(doc)


def to_json(doc: Document, *, indent: int | None = 2) -> str:
    return json.dumps(to_dict(doc), indent=indent, ensure_ascii=False, sort_keys=False)


def _run_from_dict(d: dict[str, Any]) -> Run:
    highlight = d.get("highlight")
    return Run(
        text=d["text"],
        font=d["font"],
        size=d["size"],
        bold=d["bold"],
        italic=d["italic"],
        color=tuple(d["color"]),
        underline=d.get("underline", False),
        highlight=tuple(highlight) if highlight else None,
    )


def _rect_from_dict(d: dict[str, Any] | None) -> Rect | None:
    if d is None:
        return None
    return Rect(x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"])


def _paragraph_from_dict(d: dict[str, Any]) -> Paragraph:
    return Paragraph(
        text=d["text"],
        runs=tuple(_run_from_dict(r) for r in d["runs"]),
        rect=_rect_from_dict(d["rect"]),  # type: ignore[arg-type]
        origin=tuple(d["origin"]),
        align=d["align"],
        leading=d["leading"],
        size=d["size"],
        font=d["font"],
        color=tuple(d["color"]),
        indent=d.get("indent", 0.0),
        hang_x0=d.get("hang_x0"),
        starts_item=d.get("starts_item", False),
        clip=_rect_from_dict(d.get("clip")),
    )


def _page_from_dict(d: dict[str, Any]) -> Page:
    return Page(
        number=d["number"],
        width=d["width"],
        height=d["height"],
        paragraphs=tuple(_paragraph_from_dict(p) for p in d.get("paragraphs", [])),
    )


def from_dict(d: dict[str, Any]) -> Document:
    return Document(
        source=d["source"],
        pages=tuple(_page_from_dict(p) for p in d.get("pages", [])),
    )


def from_json(s: str) -> Document:
    return from_dict(json.loads(s))
