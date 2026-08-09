"""Validated upload handling.

Everything here runs BEFORE a byte of the upload reaches any pipeline
code -- extension allowlist, size cap, page-count cap, and a magic-byte
sniff that catches a renamed file (a `.exe` saved as `report.pdf`)
independently of its claimed extension. Client-supplied filenames are
never used as filesystem paths: each upload gets a random `file_id`
directory, and the original name is kept only as metadata.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz

from palimpsest.pdf.classify import Kind, classify_pdf

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_PDF_PAGES = 500

_PDF_EXT = {".pdf"}
_OFFICE_EXT = {".docx", ".pptx", ".xlsx", ".xls"}
ALLOWED_EXTENSIONS = _PDF_EXT | _OFFICE_EXT

_MAGIC_BY_EXT = {
    ".pdf": (b"%PDF-",),
    # .docx/.pptx/.xlsx are all ZIP containers (OOXML); .xls (legacy
    # binary) has its own OLE2 signature.
    ".docx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}


class UploadRejected(Exception):
    """Carries a message safe to return to the client as-is -- never
    includes the server-side path or any exception internals."""


@dataclass(frozen=True)
class UploadedFile:
    file_id: str
    name: str
    """The client's original filename, kept as display metadata only --
    never used to build a filesystem path (see `_safe_name`)."""
    path: Path
    kind: Kind | str
    """A PDF `Kind`, or the literal string "office" for anything else."""
    pages: int | None
    size: int
    visitor_id: str = "local"
    """Which browser-generated visitor uploaded this (see
    `server/routes.py::_visitor_id`) -- `"local"` matches that module's
    `_LOCAL_VISITOR` sentinel exactly (duplicated as a literal here, not
    imported, since `uploads.py` is a layer below `routes.py` and must
    not import back up from it). `AppState.get_upload` (`app.py`) uses
    this to refuse any request for a file id that doesn't belong to the
    requesting visitor."""


def _safe_name(name: str) -> str:
    """Rejects (never silently strips) anything with a directory
    component, a null byte, or an empty/"."/".." basename -- a name like
    `../../etc/passwd.pdf` is refused outright rather than quietly
    reduced to `passwd.pdf`, since silent sanitization would mask
    exactly the kind of client bug or probe this check exists to catch."""
    if "\x00" in name:
        raise UploadRejected("invalid filename")
    candidate = Path(name).name
    if not candidate or candidate in (".", "..") or candidate != name:
        raise UploadRejected("invalid filename")
    return candidate


def validate_and_save(
    raw_name: str,
    content: bytes,
    uploads_dir: Path,
    visitor_id: str = "local",
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> UploadedFile:
    """Validate `content` against `raw_name`'s extension and save it
    under a fresh `file_id` directory inside `uploads_dir`. Raises
    `UploadRejected` (never a bare exception) for anything invalid --
    callers turn that into an HTTP 400 with the message as-is.

    `max_bytes` defaults to the module constant so every existing caller
    (including every test in `test_server_uploads.py`) is unaffected --
    the server route passes `config.limits.max_upload_bytes` instead,
    which makes the cap overridable via `[limits]` without a code
    change (see `config.model.LimitsConfig`)."""
    name = _safe_name(raw_name)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(
            f"unsupported file type {ext!r} (allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))})"
        )

    if len(content) == 0:
        raise UploadRejected("empty file")
    if len(content) > max_bytes:
        raise UploadRejected(
            f"file too large ({len(content):,} bytes; max {max_bytes:,})"
        )

    magics = _MAGIC_BY_EXT[ext]
    if not any(content.startswith(m) for m in magics):
        raise UploadRejected(f"{name}: content does not match a valid {ext} file")

    file_id = uuid.uuid4().hex
    dest_dir = uploads_dir / file_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / name
    dest_path.write_bytes(content)

    kind: Kind | str
    pages: int | None
    if ext == ".pdf":
        try:
            doc = fitz.open(str(dest_path))
            pages = len(doc)
            doc.close()
        except Exception as e:
            dest_path.unlink(missing_ok=True)
            raise UploadRejected(f"{name}: not a readable PDF ({e})") from e
        if pages > MAX_PDF_PAGES:
            dest_path.unlink(missing_ok=True)
            raise UploadRejected(f"{name}: {pages} pages exceeds the {MAX_PDF_PAGES}-page limit")
        kind = classify_pdf(str(dest_path))
    else:
        kind = "office"
        # Not computed eagerly: a real page count needs a LibreOffice
        # conversion (see office.render), which is too slow to run
        # inline in an upload request. `GET /pages/{n}.png` converts
        # and caches on first request instead.
        pages = None

    return UploadedFile(
        file_id=file_id, name=name, path=dest_path, kind=kind, pages=pages, size=len(content),
        visitor_id=visitor_id,
    )
