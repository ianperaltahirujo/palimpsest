from palimpsest.core.ir import (
    Document,
    Page,
    Paragraph,
    Rect,
    Run,
    from_dict,
    from_json,
    to_dict,
    to_json,
)


def _sample_document() -> Document:
    run = Run(
        text="Hola mundo", font="Helvetica", size=11.0, bold=False, italic=False,
        color=(0.0, 0.0, 0.0),
    )
    para = Paragraph(
        text="Hola mundo",
        runs=(run,),
        rect=Rect(x0=10.0, y0=20.0, x1=100.0, y1=35.0),
        origin=(10.0, 30.0),
        align="left",
        leading=13.0,
        size=11.0,
        font="Helvetica",
        color=(0.0, 0.0, 0.0),
    )
    page = Page(number=0, width=612.0, height=792.0, paragraphs=(para,))
    return Document(source="sample.pdf", pages=(page,))


def test_rect_width_height():
    r = Rect(x0=10.0, y0=20.0, x1=100.0, y1=35.0)
    assert r.width == 90.0
    assert r.height == 15.0


def test_to_dict_from_dict_round_trip():
    doc = _sample_document()
    restored = from_dict(to_dict(doc))
    assert restored == doc


def test_to_json_from_json_round_trip():
    doc = _sample_document()
    restored = from_json(to_json(doc))
    assert restored == doc


def test_json_is_stable_and_readable():
    doc = _sample_document()
    text = to_json(doc)
    assert "Hola mundo" in text
    assert "sample.pdf" in text


def test_paragraph_optional_fields_default_sensibly():
    para = Paragraph(
        text="x", runs=(), rect=Rect(0, 0, 1, 1), origin=(0.0, 0.0),
        align="left", leading=1.0, size=1.0, font="Helvetica", color=(0.0, 0.0, 0.0),
    )
    assert para.indent == 0.0
    assert para.hang_x0 is None
    assert para.starts_item is False
    assert para.clip is None


def test_paragraph_with_clip_round_trips():
    para = Paragraph(
        text="x", runs=(), rect=Rect(0, 0, 1, 1), origin=(0.0, 0.0),
        align="left", leading=1.0, size=1.0, font="Helvetica", color=(0.0, 0.0, 0.0),
        clip=Rect(0, 0, 50, 100),
    )
    doc = Document(source="s", pages=(Page(number=0, width=1, height=1, paragraphs=(para,)),))
    restored = from_json(to_json(doc))
    assert restored.pages[0].paragraphs[0].clip == Rect(0, 0, 50, 100)


def test_empty_document_round_trips():
    doc = Document(source="empty.pdf", pages=())
    restored = from_dict(to_dict(doc))
    assert restored == doc
