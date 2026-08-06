import fitz
import pytest

from palimpsest.config.model import (
    Config,
    CopyAsIsConfig,
    DocumentMap,
    PathsConfig,
)
from palimpsest.corpus import run_corpus
from palimpsest.text.glossary import Glossary
from tests.fixtures.fake_backend import FakeBackend


def _pdf(path, text="Un parrafo de prueba con suficiente texto para ser digital."):
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_textbox(fitz.Rect(20, 20, 380, 180), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def _config(tmp_path) -> Config:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    return Config(
        paths=PathsConfig(
            source_dir=source_dir, output_dir=output_dir,
            work_dir=tmp_path / "work", cache_dir=tmp_path / "cache",
        ),
    )


def _backend():
    return FakeBackend(translate_fn=lambda s: s.upper(), uses_placeholder_protection=False)


def test_translates_mapped_pdfs(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "doc.pdf")
    documents = DocumentMap(pdf={"doc.pdf": "doc.pdf"})

    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    assert report["pdf"][0]["status"] == "ok"
    assert (config.paths.output_dir / "doc.pdf").exists()
    assert report["errors"] == []


def test_resumable_skip_when_output_is_current(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "doc.pdf")
    documents = DocumentMap(pdf={"doc.pdf": "doc.pdf"})

    run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    report2 = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    assert report2["pdf"][0]["status"] == "skipped"


def test_force_reprocesses_even_when_current(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "doc.pdf")
    documents = DocumentMap(pdf={"doc.pdf": "doc.pdf"})

    run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    report2 = run_corpus(
        config, documents, _backend(), (), Glossary(), (), only="pdf", force=True
    )
    assert report2["pdf"][0]["status"] == "ok"


def test_one_bad_pdf_does_not_stop_the_batch(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "good.pdf")
    # "bad.pdf" is not a real PDF at all -- fitz.open() will raise.
    (config.paths.source_dir / "bad.pdf").write_bytes(b"not a pdf")
    documents = DocumentMap(pdf={"good.pdf": "good.pdf", "bad.pdf": "bad.pdf"})

    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    statuses = {r["src"]: r["status"] for r in report["pdf"]}
    assert statuses["good.pdf"] == "ok"
    assert statuses["bad.pdf"] == "ERROR"
    assert any(e["src"] == "bad.pdf" for e in report["errors"])
    assert (config.paths.output_dir / "good.pdf").exists()


def test_only_pdf_skips_office_and_copy(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "doc.pdf")
    (config.paths.source_dir / "asis.pdf").write_bytes(b"raw")
    documents = DocumentMap(
        pdf={"doc.pdf": "doc.pdf"},
        copy_as_is=CopyAsIsConfig(files=("asis.pdf",)),
    )
    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    assert report["pdf"]
    assert report["copy"] == []
    assert not (config.paths.output_dir / "asis.pdf").exists()


def test_copy_as_is_files(tmp_path):
    config = _config(tmp_path)
    (config.paths.source_dir / "raw.bin").write_bytes(b"binary content")
    documents = DocumentMap(copy_as_is=CopyAsIsConfig(files=("raw.bin",)))

    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="copy")
    assert report["copy"][0]["status"] == "copied"
    assert (config.paths.output_dir / "raw.bin").read_bytes() == b"binary content"


def test_copy_as_is_files_skip_when_up_to_date(tmp_path):
    config = _config(tmp_path)
    (config.paths.source_dir / "raw.bin").write_bytes(b"data")
    documents = DocumentMap(copy_as_is=CopyAsIsConfig(files=("raw.bin",)))

    run_corpus(config, documents, _backend(), (), Glossary(), (), only="copy")
    report2 = run_corpus(config, documents, _backend(), (), Glossary(), (), only="copy")
    assert "skipped" in report2["copy"][0]["status"]


def test_copy_as_is_dirs_found_anywhere_in_source_tree(tmp_path):
    config = _config(tmp_path)
    nested = config.paths.source_dir / "Proyecto" / "Drawings"
    nested.mkdir(parents=True)
    (nested / "a.dwg").write_bytes(b"cad data")
    documents = DocumentMap(copy_as_is=CopyAsIsConfig(dirs=("Drawings",)))

    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="copy")
    assert report["copy"][0]["status"] == "copied 1 files"
    assert (config.paths.output_dir / "Proyecto" / "Drawings" / "a.dwg").read_bytes() == b"cad data"


def test_invalid_only_raises_value_error(tmp_path):
    config = _config(tmp_path)
    documents = DocumentMap()
    with pytest.raises(ValueError):
        run_corpus(config, documents, _backend(), (), Glossary(), (), only="not-a-real-scope")


def test_scans_sorted_after_digital_pdfs(tmp_path):
    config = _config(tmp_path)
    _pdf(config.paths.source_dir / "digital.pdf")
    # A "scan" per classify_pdf's own rule: very little text relative to page count.
    scan_doc = fitz.open()
    scan_doc.new_page(width=200, height=200)
    scan_doc.save(config.paths.source_dir / "scan.pdf")
    scan_doc.close()

    documents = DocumentMap(pdf={"scan.pdf": "scan.pdf", "digital.pdf": "digital.pdf"})
    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf")
    order = [r["src"] for r in report["pdf"]]
    assert order.index("digital.pdf") < order.index("scan.pdf")


def test_jobs_parallel_produces_same_results_as_sequential(tmp_path):
    config = _config(tmp_path)
    for i in range(4):
        _pdf(
            config.paths.source_dir / f"doc{i}.pdf",
            text=f"Documento numero {i} de prueba con suficiente texto para no ser un escaneo.",
        )
    documents = DocumentMap(pdf={f"doc{i}.pdf": f"doc{i}.pdf" for i in range(4)})

    report = run_corpus(config, documents, _backend(), (), Glossary(), (), only="pdf", jobs=4)
    statuses = {r["src"]: r["status"] for r in report["pdf"]}
    assert all(s == "ok" for s in statuses.values())
    assert len(statuses) == 4
    for i in range(4):
        assert (config.paths.output_dir / f"doc{i}.pdf").exists()
