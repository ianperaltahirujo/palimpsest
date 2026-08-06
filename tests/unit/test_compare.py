import fitz
from PIL import Image

from palimpsest.qa.compare import build_dual_pdf, render_page, side_by_side


def _make_pdf(path, text="Hola mundo"):
    doc = fitz.open()
    page = doc.new_page(width=200, height=150)
    page.insert_text((20, 40), text, fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()


def test_render_page_returns_image(tmp_path):
    pdf = tmp_path / "a.pdf"
    _make_pdf(pdf)
    img = render_page(pdf, 0, dpi=72)
    assert isinstance(img, Image.Image)
    assert img.width > 0 and img.height > 0


def test_side_by_side_writes_a_file_no_import_time_directory(tmp_path):
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    _make_pdf(src, "Original")
    _make_pdf(out, "Translated")
    dest = tmp_path / "reports" / "compare.png"
    result = side_by_side(src, out, [0], dest, dpi=72)
    assert result == dest
    assert dest.exists()


def test_side_by_side_multi_page_stacks_vertically(tmp_path):
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=200, height=150)
        page.insert_text((20, 40), f"page {i}", fontsize=14, fontname="helv")
    doc.save(src)
    doc.close()
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=200, height=150)
        page.insert_text((20, 40), f"PAGE {i}", fontsize=14, fontname="helv")
    doc.save(out)
    doc.close()

    dest = tmp_path / "compare.png"
    side_by_side(src, out, [0, 1], dest, dpi=72)
    img = Image.open(dest)
    single_page_height = 150 * (72 / 72)  # dpi 72 == 1:1 with point size, roughly
    assert img.height > single_page_height  # taller than one tile -- stacked


def test_build_dual_pdf_interleaves_source_and_output_pages(tmp_path):
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=200, height=150)
        page.insert_text((20, 40), f"fuente {i}", fontsize=14, fontname="helv")
    doc.save(src)
    doc.close()
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=200, height=150)
        page.insert_text((20, 40), f"SOURCE {i}", fontsize=14, fontname="helv")
    doc.save(out)
    doc.close()

    dest = tmp_path / "dual.pdf"
    result = build_dual_pdf(src, out, dest)
    assert result == dest
    assert dest.exists()

    dual = fitz.open(dest)
    assert len(dual) == 4  # 2 source + 2 output pages, interleaved
    texts = [dual[i].get_text() for i in range(4)]
    dual.close()
    assert "fuente 0" in texts[0]
    assert "SOURCE 0" in texts[1]
    assert "fuente 1" in texts[2]
    assert "SOURCE 1" in texts[3]


def test_build_dual_pdf_truncates_to_shorter_document(tmp_path):
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=200, height=150)
    doc.save(src)
    doc.close()
    doc = fitz.open()
    doc.new_page(width=200, height=150)
    doc.save(out)
    doc.close()

    dest = tmp_path / "dual.pdf"
    build_dual_pdf(src, out, dest)
    dual = fitz.open(dest)
    assert len(dual) == 2  # min(3, 1) pages, interleaved
    dual.close()
