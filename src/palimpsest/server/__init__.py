"""Local FastAPI service wrapping the palimpsest pipeline.

Everything under this package is optional -- installed via the
`[server]` extra (`pip install "palimpsest-translate[server]"`) and
never imported by `palimpsest.cli` unless `palimpsest serve` is the
subcommand actually invoked. A CLI-only install stays free of FastAPI/
uvicorn/python-multipart, exactly like `[anthropic]`/`[gemini]`/`[ocr]`.

Local-first by design, not by omission -- see `app.create_app`'s
docstring for what that means concretely (no auth, no cloud storage,
loopback-only by default). This is a desktop-style local tool, not a
multi-tenant hosted service.
"""

from __future__ import annotations
