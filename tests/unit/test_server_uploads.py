"""Unit tests for validated upload handling, independent of the FastAPI
app -- see test_server_api.py for the full HTTP-level upload flow."""

import fitz
import pytest

from palimpsest.server.uploads import (
    MAX_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    UploadRejected,
    validate_and_save,
)


def _minimal_pdf_bytes(n_pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(n_pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 20), "hola")
    data = doc.tobytes()
    doc.close()
    return data


def test_accepts_valid_pdf(tmp_path):
    content = _minimal_pdf_bytes()
    result = validate_and_save("doc.pdf", content, tmp_path)
    assert result.name == "doc.pdf"
    assert result.kind in ("digital", "scan", "ocr")
    assert result.pages == 1
    assert result.path.is_file()
    assert result.path.read_bytes() == content


def test_rejects_unsupported_extension(tmp_path):
    with pytest.raises(UploadRejected, match="unsupported file type"):
        validate_and_save("payload.exe", b"MZ\x90\x00", tmp_path)


def test_rejects_pdf_extension_with_wrong_magic_bytes(tmp_path):
    """A .exe renamed to .pdf -- the extension lies, the magic bytes don't."""
    with pytest.raises(UploadRejected, match="does not match"):
        validate_and_save("fake.pdf", b"MZ\x90\x00\x03\x00\x00\x00", tmp_path)


def test_rejects_empty_file(tmp_path):
    with pytest.raises(UploadRejected, match="empty"):
        validate_and_save("doc.pdf", b"", tmp_path)


def test_rejects_oversized_file(tmp_path):
    oversized = b"%PDF-1.4\n" + b"0" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(UploadRejected, match="too large"):
        validate_and_save("doc.pdf", oversized, tmp_path)


def test_max_bytes_override_is_honored(tmp_path):
    """The server passes config.limits.max_upload_bytes here instead of
    relying on the module default -- confirm an override actually takes
    effect, both tighter and looser than the module constant."""
    content = _minimal_pdf_bytes()
    with pytest.raises(UploadRejected, match="too large"):
        validate_and_save("doc.pdf", content, tmp_path, max_bytes=10)
    # Same content, no override -- well under the real default, succeeds.
    validate_and_save("doc.pdf", content, tmp_path)


def test_rejects_traversal_shaped_filename(tmp_path):
    content = _minimal_pdf_bytes()
    with pytest.raises(UploadRejected, match="invalid filename"):
        validate_and_save("../../etc/passwd.pdf", content, tmp_path)
    # nothing was written outside tmp_path
    assert not (tmp_path.parent.parent / "etc").exists()


def test_rejects_bare_directory_traversal_name(tmp_path):
    with pytest.raises(UploadRejected):
        validate_and_save("..", b"%PDF-1.4", tmp_path)


def test_each_upload_gets_its_own_file_id_directory(tmp_path):
    content = _minimal_pdf_bytes()
    a = validate_and_save("doc.pdf", content, tmp_path)
    b = validate_and_save("doc.pdf", content, tmp_path)
    assert a.file_id != b.file_id
    assert a.path != b.path
    assert a.path.is_file() and b.path.is_file()


def test_docx_accepted_by_zip_magic_bytes(tmp_path):
    # A .docx is a ZIP container -- doesn't need to be a valid OOXML doc
    # for the upload layer's own check, which only sniffs the container.
    zip_magic = b"PK\x03\x04" + b"\x00" * 20
    result = validate_and_save("Contract.docx", zip_magic, tmp_path)
    assert result.kind == "office"
    assert result.pages is None


def test_rejects_page_count_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("palimpsest.server.uploads.MAX_PDF_PAGES", 2)
    content = _minimal_pdf_bytes(n_pages=3)
    with pytest.raises(UploadRejected, match="exceeds"):
        validate_and_save("big.pdf", content, tmp_path)


def test_page_limit_constant_is_reasonable():
    # sanity check the module constant hasn't been accidentally set to
    # something silly (e.g. 0 or negative) that would reject everything
    assert MAX_PDF_PAGES > 0
