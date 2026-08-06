"""Classify a PDF as digital text, an existing OCR layer, or a pure scan.

The distinction drives the whole pipeline: a "scan" needs OCR before
anything else can run, an "ocr" PDF already has a text layer but it
carries no real font/weight information (see `pdf.inkstyle`), and a
"digital" PDF can be extracted and redrawn directly.
"""

from __future__ import annotations

from typing import Literal

import fitz

Kind = Literal["digital", "ocr", "scan"]


def classify_pdf(path: str) -> Kind:
    doc = fitz.open(path)
    try:
        n = len(doc)
        chars = 0
        fonts = set()
        for page in doc:
            chars += len(page.get_text().strip())
            for f in page.get_fonts(full=True):
                fonts.add(f[3])
        if n and chars < 40 * n:
            return "scan"
        if fonts and all("GlyphLess" in f for f in fonts):
            return "ocr"
        return "digital"
    finally:
        doc.close()
