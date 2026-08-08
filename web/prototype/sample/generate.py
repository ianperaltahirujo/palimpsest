"""Generates the wipe-demo sample pair -- public/sample/{source,output}.png
and src/sample/layout.json (the English page's real IR, for edit mode) --
a miniature stand-in for what translate_pdf_document() actually produces.
Content is entirely fictional (the de-identified cast from
docs/design/protected-entities.md: Grupo Meridian, Banco Litoral, Andrés
Carreño) -- never run against real corpus documents, and this script must
never grow a way to point at one (no --from path, no reading argv) --
tools/scrub_check.py gates CI and this repo is public. Not part of the
prototype at runtime; run once to regenerate the checked-in files.

    python generate.py

layout.json is NOT hand-built. build() constructs the page, then the REAL
extractor (palimpsest.pdf.layout.extract_paragraphs + page_to_ir) runs
over it, so the fixture is definitionally the same shape production
emits -- alignment, leading, and paragraph boundaries all came out of the
actual functions, not a guess at their shape. If a boundary looks wrong
for the demo, fix it by adjusting the synthetic page geometry below and
re-running; never hand-edit the generated JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from palimpsest.core import ir
from palimpsest.pdf import layout

PAGE = fitz.paper_rect("letter")
MARGIN = 72
BODY_W = PAGE.width - 2 * MARGIN
SERIF = "georgia" if "georgia" not in fitz.Font.__dict__ else "georgia"

RENDER_ZOOM = 1.6


def _para(page, rect, text, *, size=10.5, bold=False, align=0, color=(0.08, 0.09, 0.11)):
    fontname = "Georgia-Bold" if bold else "Georgia"
    fontfile = r"C:\Windows\Fonts\georgiab.ttf" if bold else r"C:\Windows\Fonts\georgia.ttf"
    page.insert_font(fontname=fontname, fontfile=fontfile)
    page.insert_textbox(
        rect, text, fontname=fontname, fontsize=size, color=color,
        align=align, lineheight=1.42,
    )


def build(lang: str) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=PAGE.width, height=PAGE.height)

    if lang == "es":
        kicker = "REPÚBLICA DOMINICANA — REGISTRO MERCANTIL"
        title = "ACTA CONSTITUTIVA DE FIDEICOMISO"
        subtitle = "FIDEICOMISO AURORA PLAZA"
        ref = "Expediente No. FA-0142-2026  ·  Santo Domingo de Guzmán, Distrito Nacional"
        body = (
            "En la ciudad de Santo Domingo de Guzmán, Distrito Nacional, siendo las diez "
            "horas de la mañana del día seis (6) de agosto del año dos mil veintiséis "
            "(2026), comparecen de una parte BANCO LITORAL, S.A., entidad de "
            "intermediación financiera constituida de conformidad con las leyes de la "
            "República Dominicana, actuando en su calidad de fiduciario, y de la otra "
            "parte GRUPO MERIDIAN, S.A.S., sociedad comercial debidamente organizada, "
            "actuando en su calidad de fideicomitente, quienes convienen constituir el "
            "presente fideicomiso de conformidad con las disposiciones que se detallan "
            "a continuación."
        )
        clause1_h = "PRIMERO: OBJETO DEL FIDEICOMISO"
        clause1 = (
            "El presente fideicomiso tiene por objeto la administración de los bienes "
            "descritos en el Anexo A, así como la ejecución de las obligaciones "
            "contractuales asumidas por las partes en virtud del contrato de fecha "
            "veintitrés (23) de julio de dos mil veintiséis (2026)."
        )
        clause2_h = "SEGUNDO: PATRIMONIO FIDEICOMITIDO"
        clause2 = (
            "El patrimonio fideicomitido asciende a la suma de RD$48,750,000.00 "
            "(cuarenta y ocho millones setecientos cincuenta mil pesos dominicanos), "
            "según consta en el avalúo practicado por la firma independiente designada "
            "de común acuerdo entre las partes."
        )
        sign_h = "TESTIGOS DE HONOR"
        sign1 = "Andrés Carreño\nApoderado Especial\nGrupo Meridian, S.A.S."
        sign2 = "Lucía Fernández Roa\nDirectora Fiduciaria\nBanco Litoral, S.A."
        footer = "Página 1 de 1  ·  Registrado ante la Dirección General de Impuestos Internos"
    else:
        kicker = "DOMINICAN REPUBLIC — COMMERCIAL REGISTRY"
        title = "TRUST FORMATION DEED"
        subtitle = "AURORA PLAZA TRUST"
        ref = "File No. FA-0142-2026  ·  Santo Domingo de Guzmán, Distrito Nacional"
        body = (
            "In the city of Santo Domingo de Guzmán, Distrito Nacional, at ten o'clock "
            "in the morning on the sixth (6th) day of August, two thousand twenty-six "
            "(2026), the following parties appear: on one part, BANCO LITORAL, S.A., a "
            "financial intermediation entity organized under the laws of the Dominican "
            "Republic, acting in its capacity as trustee, and on the other part, GRUPO "
            "MERIDIAN, S.A.S., a duly organized commercial company, acting in its "
            "capacity as settlor, who agree to constitute this trust in accordance with "
            "the provisions set forth below."
        )
        clause1_h = "FIRST: PURPOSE OF THE TRUST"
        clause1 = (
            "This trust has as its purpose the administration of the assets described "
            "in Exhibit A, as well as the performance of the contractual obligations "
            "undertaken by the parties under the agreement dated July twenty-third "
            "(23rd), two thousand twenty-six (2026)."
        )
        clause2_h = "SECOND: TRUST ESTATE"
        clause2 = (
            "The trust estate amounts to RD$48,750,000.00 (forty-eight million seven "
            "hundred fifty thousand Dominican pesos), as recorded in the appraisal "
            "conducted by the independent firm jointly designated by the parties."
        )
        sign_h = "WITNESSES OF HONOR"
        sign1 = "Andrés Carreño\nSpecial Attorney-in-Fact\nGrupo Meridian, S.A.S."
        sign2 = "Lucía Fernández Roa\nTrust Director\nBanco Litoral, S.A."
        footer = "Page 1 of 1  ·  Recorded with the Directorate General of Internal Revenue"

    y = MARGIN
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 16), kicker,
          size=8.2, bold=True, color=(0.42, 0.05, 0.32))
    y += 26
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 30), title,
          size=17.5, bold=True)
    y += 30
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 20), subtitle,
          size=11.5, bold=True, color=(0.02, 0.20, 0.55))
    y += 22
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 18), ref,
          size=8.6, color=(0.35, 0.37, 0.40))
    y += 24
    page.draw_line((MARGIN, y), (MARGIN + BODY_W, y), color=(0.76, 0.78, 0.82), width=0.7)
    y += 22

    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 110), body, size=10.3)
    y += 128

    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 20), clause1_h,
          size=10.3, bold=True)
    y += 24
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 62), clause1, size=10.3)
    y += 78

    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 20), clause2_h,
          size=10.3, bold=True)
    y += 24
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 62), clause2, size=10.3)
    y += 88

    page.draw_line((MARGIN, y), (MARGIN + BODY_W, y), color=(0.76, 0.78, 0.82), width=0.7)
    y += 18
    _para(page, fitz.Rect(MARGIN, y, MARGIN + BODY_W, y + 14), sign_h,
          size=8.2, bold=True, color=(0.42, 0.05, 0.32))
    y += 24

    col_w = BODY_W / 2 - 14
    _para(page, fitz.Rect(MARGIN, y, MARGIN + col_w, y + 60), sign1, size=9.6)
    _para(page, fitz.Rect(MARGIN + col_w + 28, y, MARGIN + BODY_W, y + 60), sign2, size=9.6)

    _para(page, fitz.Rect(MARGIN, PAGE.height - MARGIN + 8, MARGIN + BODY_W,
                           PAGE.height - MARGIN + 22), footer,
          size=7.6, color=(0.45, 0.47, 0.50))

    return doc


def build_layout_envelope(
    en_doc: fitz.Document, png_name: str, px_width: int, px_height: int
) -> dict:
    """Runs the real extractor over the already-built English page and
    wraps its IR in the envelope the prototype (and later, the real
    /api/jobs/{id}/layout endpoint) expects.

    `source`/`pages` are byte-for-byte `ir.to_dict(Document)` -- nothing
    reshaped for the browser -- so a server-side round trip is exactly
    `ir.from_dict(payload["pages"] and friends)` with no shim.
    `_page_from_dict`/`_paragraph_from_dict` look up fields by name and
    ignore anything extra, so `render` living alongside `pages` (rather
    than inside it) is safe: raster metadata is a presentation concern,
    not something `ir.Page` should know about.

    Coordinates stay in PDF points, exactly as the library produces them
    -- PyMuPDF page space is already top-left-origin with y increasing
    downward, so there is deliberately NO y-flip anywhere in this file or
    in the browser code that consumes this envelope.
    """
    page = en_doc[0]
    paras = layout.extract_paragraphs(page, min_size=3.0)
    ir_page = layout.page_to_ir(page, paras)
    document = ir.Document(source="trust-deed-aurora.en.pdf", pages=(ir_page,))
    doc_dict = ir.to_dict(document)
    return {
        "schema": 1,
        "source": doc_dict["source"],
        "pages": doc_dict["pages"],
        "render": {
            "zoom": RENDER_ZOOM,
            "pages": [
                {"number": 0, "png": png_name, "px_width": px_width, "px_height": px_height},
            ],
        },
    }


PUBLIC_SAMPLE = Path(__file__).resolve().parent.parent / "public" / "sample"
SRC_SAMPLE = Path(__file__).resolve().parent.parent / "src" / "sample"


def main():
    PUBLIC_SAMPLE.mkdir(parents=True, exist_ok=True)
    SRC_SAMPLE.mkdir(parents=True, exist_ok=True)

    pixmaps: dict[str, fitz.Pixmap] = {}
    docs: dict[str, fitz.Document] = {}
    for lang, out in (("es", "source.png"), ("en", "output.png")):
        doc = build(lang)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
        pix.save(str(PUBLIC_SAMPLE / out))
        print(f"{out}: {pix.width}x{pix.height}")
        pixmaps[lang] = pix
        docs[lang] = doc

    en_pix = pixmaps["en"]
    envelope = build_layout_envelope(docs["en"], "output.png", en_pix.width, en_pix.height)
    layout_json = json.dumps(envelope, indent=2, ensure_ascii=False)

    # Raster assets are static files the browser fetches by URL, so they
    # live in public/ (Vite serves it verbatim, unprocessed). layout.json
    # is imported as a JS module (`import layout from "../sample/layout.json"`
    # in CompareStage.jsx) -- Vite's module graph does not cover public/,
    # so this one file lives under src/ instead. No more layout.js: that
    # existed only because fetch() was blocked under file://, which Vite's
    # dev server and build output don't have.
    (SRC_SAMPLE / "layout.json").write_text(layout_json, encoding="utf-8")
    print(f"layout.json: {len(envelope['pages'][0]['paragraphs'])} paragraphs")

    for doc in docs.values():
        doc.close()


if __name__ == "__main__":
    main()
