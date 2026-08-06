# Contributing

## Setup

```bash
git clone https://github.com/ianperaltahirujo/palimpsest.git
cd palimpsest
pip install -e ".[all,dev]"
pytest
ruff check .
mypy
```

## Rules that are load-bearing, not just style preferences

This codebase was extracted from a real client pipeline, and a couple of
rules exist specifically to keep it that way:

- **Never commit anything under `private/`, `.palimpsest/`, or `corpus/`.**
  These paths are reserved for user-specific document maps, entity lists,
  and translation caches, and are gitignored for a reason — the project's
  own origin included real confidential client data that had to be kept
  out.
- **Run `python tools/scrub_check.py --history` before opening a PR** if
  you've added or edited anything under `docs/` or `examples/`. It's also
  enforced in CI.
- No test may make a real network call. Mark anything that legitimately
  needs one `@pytest.mark.network` (or `@pytest.mark.ocr` for a real
  Tesseract dependency) — both are deselected in CI by default.

## Beyond that

Open an issue before a large PR, keep changes scoped to one concern, and
prefer extending an existing module over introducing a new abstraction
layer. If you're touching `pdf.layout`, `pdf.render`, or `text.protect`,
read the relevant section of `docs/design/` first — several behaviors that
look like they could be simplified are there because of a specific,
documented regression.
