"""Rebuilds the GRUPO -> CLUSTER regression at the pdf.pipeline layer: a
FakeBackend that mistranslates the bare fragment "GRUPO"/"MERIDIAN" must
never actually be invoked with it, across every call path this module
exposes -- the top-level paragraph loop, the label-split "rest" path, and
translate_paragraph's own head/rest split.
"""

from __future__ import annotations

import fitz

from palimpsest.config.model import Config, FontsConfig, PathsConfig, ThresholdsConfig
from palimpsest.pdf import layout
from palimpsest.pdf.fontmap import FontResolver
from palimpsest.pdf.pipeline import (
    dominant_style,
    process_document,
    split_prefix,
    style_segments,
    translate_paragraph,
    translate_pdf_document,
    translate_with_prefix,
)
from palimpsest.pdf.render import RenderContext
from palimpsest.text.glossary import Glossary
from palimpsest.text.protect import EntityGuard
from palimpsest.translate.translator import Translator
from tests.fixtures.fake_backend import FakeBackend

ENTITIES = ("Grupo Meridian", "Banco Litoral")

STYLE_BOLD = ("Helvetica", 11.0, True, False, (0.0, 0.0, 0.0))
STYLE_REGULAR = ("Helvetica", 11.0, False, False, (0.0, 0.0, 0.0))


def _para(text: str, runs: list[dict]) -> layout.Para:
    return layout.Para(
        text=text, runs=runs, rect=fitz.Rect(0, 0, 100, 20), origin=(0, 10),
        align="left", leading=13.0, size=11.0, font="Helvetica",
        color=(0, 0, 0), page=0, indent=0.0, line_rects=[fitz.Rect(0, 0, 100, 20)],
        block_no=0, clip=None, hang_x0=None, starts_item=False,
    )


def _translator(translate_fn, entities=ENTITIES) -> Translator:
    backend = FakeBackend(translate_fn=translate_fn, uses_placeholder_protection=False)
    return Translator(
        "unused.json", backend, cache_namespace="ns", entities=entities, verbose=False,
    )


class _NeverBackend:
    """Fails the test if ever called with a bare protected fragment."""

    name = "never"
    prefers_batch = False
    max_batch = 20
    uses_placeholder_protection = False

    def __init__(self, forbidden: set[str]):
        self.forbidden = forbidden
        self.calls: list[str] = []

    def translate(self, text, ctx):
        from palimpsest.translate.backend import TranslationResult

        assert text.strip() not in self.forbidden, f"backend called with bare fragment: {text!r}"
        self.calls.append(text)
        return TranslationResult(text=text.upper(), status="ok")

    def translate_batch(self, texts, ctx):
        return [self.translate(t, ctx) for t in texts]

    def estimate(self, texts, ctx):
        return None


# -- split_prefix / translate_with_prefix ------------------------------------

def test_split_prefix_peels_list_marker():
    prefix, rest = split_prefix("a) el arrendatario pagara")
    assert prefix == "a) "
    assert rest == "el arrendatario pagara"


def test_split_prefix_peels_ordinal():
    prefix, rest = split_prefix("DECIMO CUARTO. Las partes acuerdan")
    assert prefix == "FOURTEENTH. "
    assert rest == "Las partes acuerdan"


def test_split_prefix_no_marker_returns_empty_prefix():
    prefix, rest = split_prefix("Un parrafo normal sin marcador")
    assert prefix == ""
    assert rest == "Un parrafo normal sin marcador"


def test_translate_with_prefix_reattaches_prefix_verbatim():
    tr = _translator(lambda s: s.upper())
    en, status = translate_with_prefix("a) el arrendatario pagara", tr)
    assert status == "ok"
    assert en == "a) EL ARRENDATARIO PAGARA"


def test_translate_with_prefix_bare_prefix_no_remainder():
    tr = _translator(lambda s: s.upper())
    en, status = translate_with_prefix("DECIMO.", tr)
    assert status == "ok"
    assert en == "TENTH."


# -- style_segments / dominant_style ------------------------------------

def test_style_segments_merges_adjacent_same_style_runs():
    runs = [
        {"text": "Hola ", "style": STYLE_REGULAR},
        {"text": "mundo", "style": STYLE_REGULAR},
        {"text": " fin", "style": STYLE_BOLD},
    ]
    segs = style_segments(_para("Hola mundo fin", runs))
    assert segs == [("Hola mundo", STYLE_REGULAR), (" fin", STYLE_BOLD)]


def test_dominant_style_is_longest_segment():
    segs = [("short", STYLE_BOLD), ("a much longer segment of text", STYLE_REGULAR)]
    assert dominant_style(segs) == STYLE_REGULAR


# -- translate_paragraph: the GRUPO -> CLUSTER regression -------------------

def test_translate_paragraph_label_split_protects_fragment_rest():
    """A genuine label ('Ref:') followed by body text that happens to be
    a bare protected-entity fragment ('Meridian') must not reach the
    backend with that fragment alone. The body run is made longer than
    the label run on purpose: `dominant_style` picks whichever segment's
    TEXT is longer, and the label/body split heuristic requires the
    label's style to differ from that dominant style -- with a longer
    label than body, dominant_style would pick the label's own style and
    the split would never trigger, which is a test-setup pitfall, not a
    behaviour to assert on."""
    runs = [
        {"text": "Ref:", "style": STYLE_BOLD},
        {"text": " Meridian", "style": STYLE_REGULAR},
    ]
    para = _para("Ref: Meridian", runs)
    guard = EntityGuard(ENTITIES)
    backend = _NeverBackend(forbidden={"Meridian"})
    tr = Translator("unused.json", backend, cache_namespace="ns", entities=ENTITIES, verbose=False)
    segs, status = translate_paragraph(para, tr, guard, label_max_chars=90)
    assert status == "ok"
    # "Meridian" was routed around the backend (guard.skip), not translated.
    assert any("Meridian" in text for text, _ in segs)
    assert "Meridian" not in backend.calls


def test_translate_paragraph_does_not_split_a_bare_fragment_heading():
    """OCR size-jitter can fragment 'GRUPO MERIDIAN, SRL.' into a bold
    'GRUPO' run and a non-bold 'MERIDIAN, SRL.' run -- since 'GRUPO' has
    no terminal punctuation, this must NOT be treated as a label/body
    split (which would send 'GRUPO' to MT in isolation). The whole
    paragraph text is sent to the backend as ONE unit instead -- this
    does not by itself decide whether MT is skipped entirely (that is
    `process_document`'s `guard.skip(para.text)` check, run before
    `translate_paragraph` is ever called); what this pins is that no
    fragment of the entity name is EVER passed alone."""
    runs = [
        {"text": "GRUPO", "style": STYLE_BOLD},
        {"text": " MERIDIAN, SRL.", "style": STYLE_REGULAR},
    ]
    para = _para("GRUPO MERIDIAN, SRL.", runs)
    guard = EntityGuard(ENTITIES)
    backend = _NeverBackend(forbidden={"GRUPO", "MERIDIAN, SRL."})
    tr = Translator("unused.json", backend, cache_namespace="ns", entities=ENTITIES, verbose=False)
    segs, status = translate_paragraph(para, tr, guard, label_max_chars=90)
    assert status == "ok"
    assert backend.calls == ["GRUPO MERIDIAN, SRL."]


def test_translate_paragraph_normal_prose_mentioning_entity_still_translates():
    text = "En nuestra opinion, Grupo Meridian presenta razonablemente."
    runs = [{"text": text, "style": STYLE_REGULAR}]
    para = _para(runs[0]["text"], runs)
    guard = EntityGuard(ENTITIES)
    backend = _NeverBackend(forbidden=set())
    tr = Translator("unused.json", backend, cache_namespace="ns", entities=ENTITIES, verbose=False)
    segs, status = translate_paragraph(para, tr, guard, label_max_chars=90)
    assert status == "ok"
    assert backend.calls  # actually translated, not skipped entirely


# -- process_document: end-to-end on a real (synthetic) PDF -----------------

def _config(tmp_path) -> Config:
    return Config(
        paths=PathsConfig(
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
            report_dir=tmp_path / "reports",
        ),
        thresholds=ThresholdsConfig(),
        fonts=FontsConfig(use_bundled_fallback=True),
    )


def test_process_document_translates_and_saves(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), "Hola mundo, este es un documento.",
        fontsize=12, fontname="helv", align=0,
    )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()

    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    guard = EntityGuard(())
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    tr = Translator(
        config.paths.cache_dir / "doc.json", backend, cache_namespace="ns",
        entities=(), verbose=False,
    )
    render_ctx = RenderContext(
        font_resolver=FontResolver(use_bundled_fallback=True),
        min_scale=config.thresholds.min_scale,
        justify_max_stretch=config.thresholds.justify_max_stretch,
    )
    report = process_document(src, out, "in.pdf", tr, guard, render_ctx, config, kind="digital")

    assert out.exists()
    assert report["kind"] == "digital"
    assert report["translated"] >= 1
    assert report["failed"] == []

    result_doc = fitz.open(out)
    text = result_doc[0].get_text()
    result_doc.close()
    assert "HOLA MUNDO" in text.upper() or "MUNDO" in text.upper()


def test_process_document_entity_survives_verbatim(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), "Grupo Meridian firmo el contrato ayer.",
        fontsize=12, fontname="helv", align=0,
    )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()

    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    guard = EntityGuard(ENTITIES)
    backend = FakeBackend(translate_fn=lambda s: s, uses_placeholder_protection=False)
    tr = Translator(
        config.paths.cache_dir / "doc.json", backend, cache_namespace="ns",
        entities=ENTITIES, verbose=False,
    )
    render_ctx = RenderContext(font_resolver=FontResolver(use_bundled_fallback=True))
    process_document(src, out, "in.pdf", tr, guard, render_ctx, config, kind="digital")

    result_doc = fitz.open(out)
    text = result_doc[0].get_text()
    result_doc.close()
    assert "Grupo Meridian" in text


def test_translate_pdf_document_builds_its_own_translator_and_context(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), "Un documento corto de prueba.",
        fontsize=12, fontname="helv", align=0,
    )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()
    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)

    report = translate_pdf_document(
        src, out, "in.pdf", backend, entities=(), glossary=Glossary(),
        post_rules=(), config=config, kind="digital",
    )
    assert out.exists()
    assert report["translated"] >= 1
    # cache file was created under the configured cache_dir
    assert list(config.paths.cache_dir.glob("*.json"))


def test_process_document_reports_progress_through_all_six_phases(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), "Hola mundo, este es un documento.",
        fontsize=12, fontname="helv", align=0,
    )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()

    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    guard = EntityGuard(())
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    tr = Translator(
        config.paths.cache_dir / "doc.json", backend, cache_namespace="ns",
        entities=(), verbose=False,
    )
    render_ctx = RenderContext(font_resolver=FontResolver(use_bundled_fallback=True))

    events = []
    process_document(
        src, out, "in.pdf", tr, guard, render_ctx, config,
        kind="digital", progress=events.append,
    )

    phases_seen = [e.phase for e in events]
    # classify has no "active" (it's synchronous and instant), the rest
    # all fire active-then-done in pipeline order.
    assert phases_seen[0] == "classify"
    for phase in ("ocr", "extract", "translate", "render", "save"):
        assert phase in phases_seen
    # not a scan -- OCR reports done directly, with no active event
    ocr_events = [e for e in events if e.phase == "ocr"]
    assert len(ocr_events) == 1
    assert ocr_events[0].status == "done"
    assert ocr_events[0].detail == "skipped -- not a scan"
    # every phase ends on "done"
    for phase in ("classify", "extract", "translate", "render", "save"):
        assert [e for e in events if e.phase == phase][-1].status == "done"


def test_process_document_with_no_progress_callback_is_unaffected(tmp_path):
    """progress=None (the default) must not change behaviour at all."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(
        fitz.Rect(40, 40, 360, 160), "Hola mundo.", fontsize=12, fontname="helv", align=0,
    )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()

    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    guard = EntityGuard(())
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    tr = Translator(
        config.paths.cache_dir / "doc.json", backend, cache_namespace="ns",
        entities=(), verbose=False,
    )
    render_ctx = RenderContext(font_resolver=FontResolver(use_bundled_fallback=True))
    report = process_document(src, out, "in.pdf", tr, guard, render_ctx, config, kind="digital")
    assert out.exists()
    assert report["translated"] >= 1


def test_pages_filter_only_translates_the_selected_page(tmp_path):
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=400, height=200)
        page.insert_textbox(
            fitz.Rect(40, 40, 360, 160), f"Contenido de la pagina numero {i} en espanol.",
            fontsize=12, fontname="helv", align=0,
        )
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()
    out = tmp_path / "out.pdf"
    config = _config(tmp_path)
    guard = EntityGuard(())
    backend = FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)
    tr = Translator(
        config.paths.cache_dir / "doc.json", backend, cache_namespace="ns",
        entities=(), verbose=False,
    )
    render_ctx = RenderContext(font_resolver=FontResolver(use_bundled_fallback=True))

    report = process_document(
        src, out, "in.pdf", tr, guard, render_ctx, config, kind="digital", pages={1},
    )
    assert report["paragraphs"] == 1  # only page index 1 was even extracted

    result_doc = fitz.open(out)
    page0_text = result_doc[0].get_text().upper()
    page1_text = result_doc[1].get_text().upper()
    page2_text = result_doc[2].get_text().upper()
    result_doc.close()
    # Page 0 and 2 are untouched Spanish; page 1 alone was translated.
    assert "PAGINA NUMERO 0" in page0_text
    assert "PAGINA NUMERO 2" in page2_text
    assert "PAGINA NUMERO 1" in page1_text  # backend just uppercases -- Spanish text survives
