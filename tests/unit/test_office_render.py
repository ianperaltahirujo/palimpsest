"""Unit tests for `office.render`.

Most tests mock `subprocess.run` (same convention as `test_ocr.py` for
its Tesseract dependency) so they run without LibreOffice installed.
One real end-to-end test is skipped unless `find_soffice()` actually
finds a LibreOffice install, for genuine confidence wherever it's
available -- see the module docstring for why `fitz.open()` alone
can't be trusted to prove this feature works."""

from __future__ import annotations

import os
import time

import pytest

from palimpsest.core.errors import DependencyError
from palimpsest.office import render as render_mod


def _touch(path, content=b"data"):
    path.write_bytes(content)
    return path


def test_dependency_error_when_soffice_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: None)
    src = _touch(tmp_path / "doc.docx")
    with pytest.raises(DependencyError, match="LibreOffice"):
        render_mod.ensure_preview_pdf(src, tmp_path / "preview", "key")


def test_dependency_error_for_unsupported_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "/usr/bin/soffice")
    src = _touch(tmp_path / "doc.txt")
    with pytest.raises(DependencyError, match="\\.txt"):
        render_mod.ensure_preview_pdf(src, tmp_path / "preview", "key")


def test_reuses_existing_preview_when_newer_than_source(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "/usr/bin/soffice")
    src = _touch(tmp_path / "doc.docx")
    out_dir = tmp_path / "preview"
    out_dir.mkdir()
    out = _touch(out_dir / "key.preview.pdf")
    now = time.time()
    os.utime(src, (now - 10, now - 10))
    os.utime(out, (now, now))

    called = []
    monkeypatch.setattr(render_mod.subprocess, "run", lambda *a, **kw: called.append(1))
    result = render_mod.ensure_preview_pdf(src, out_dir, "key")
    assert result == out
    assert not called  # LibreOffice never invoked -- reused the cached conversion


def test_runs_soffice_and_returns_output_path(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "/usr/bin/soffice")
    src = _touch(tmp_path / "doc.docx")
    out_dir = tmp_path / "preview"

    class _Result:
        returncode = 0
        stderr = ""

    captured_cmd = []

    def _fake_run(cmd, capture_output, text, timeout):
        captured_cmd.extend(cmd)
        # soffice's real effect: writes {stem}.pdf into --outdir.
        scratch = out_dir / ".preview-key"
        (scratch / "doc.pdf").write_bytes(b"%PDF-1.4 fake preview")
        return _Result()

    monkeypatch.setattr(render_mod.subprocess, "run", _fake_run)
    result = render_mod.ensure_preview_pdf(src, out_dir, "key")
    assert result == out_dir / "key.preview.pdf"
    assert result.read_bytes() == b"%PDF-1.4 fake preview"
    assert "--headless" in captured_cmd
    assert "--convert-to" in captured_cmd and "pdf" in captured_cmd
    assert str(src) in captured_cmd
    # The scratch dir is cleaned up, not left behind.
    assert not (out_dir / ".preview-key").exists()


def test_nonzero_returncode_raises_dependency_error(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "/usr/bin/soffice")
    src = _touch(tmp_path / "doc.docx")
    out_dir = tmp_path / "preview"

    class _Result:
        returncode = 1
        stderr = "soffice: command failed"

    monkeypatch.setattr(render_mod.subprocess, "run", lambda *a, **kw: _Result())
    with pytest.raises(DependencyError, match="LibreOffice could not convert"):
        render_mod.ensure_preview_pdf(src, out_dir, "key")


def test_missing_output_file_raises_dependency_error(tmp_path, monkeypatch):
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "/usr/bin/soffice")
    src = _touch(tmp_path / "doc.docx")
    out_dir = tmp_path / "preview"

    class _Result:
        returncode = 0
        stderr = ""

    # Never writes the expected {stem}.pdf, even though returncode says success.
    monkeypatch.setattr(render_mod.subprocess, "run", lambda *a, **kw: _Result())
    with pytest.raises(DependencyError):
        render_mod.ensure_preview_pdf(src, out_dir, "key")


@pytest.mark.skipif(
    render_mod.find_soffice() is None, reason="LibreOffice not installed on this machine"
)
def test_real_conversion_produces_a_real_multi_page_pdf(tmp_path):
    """End-to-end against the actual `soffice` binary -- the whole
    reason this module exists is that `fitz.open()` alone lies about
    Office page rendering (see the module docstring), so a test that
    only mocks the subprocess call would never catch that regression."""
    import fitz

    docx = pytest.importorskip("docx")
    src = tmp_path / "doc.docx"
    d = docx.Document()
    d.add_paragraph("Primera pagina de contenido de prueba.")
    d.add_page_break()
    d.add_paragraph("Segunda pagina de contenido de prueba.")
    d.save(str(src))

    pdf_path = render_mod.ensure_preview_pdf(src, tmp_path / "preview", "key")
    assert pdf_path.is_file()
    doc = fitz.open(str(pdf_path))
    try:
        assert len(doc) == 2
        assert "Primera pagina" in doc[0].get_text()
        assert "Segunda pagina" in doc[1].get_text()
    finally:
        doc.close()
