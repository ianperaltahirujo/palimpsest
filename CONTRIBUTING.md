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
- **After editing `README.md`, run `python tools/render_pypi_readme.py`
  and commit the resulting `README.pypi.md`.** The two files necessarily
  diverge (`README.md`'s relative links/images are what keeps GitHub's
  render free of a background box around the logo; PyPI's renderer needs
  the opposite, since it has no repo to resolve a relative path against
  at all) — see that script's own docstring for the full reasoning. CI
  fails if the generated file is out of sync with the source.

## Releasing

Only maintainers with PyPI trusted-publisher access can do this.

1. Bump the version in **both** `pyproject.toml`'s `version` and
   `src/palimpsest/__init__.py`'s `__version__` — there's no single
   source of truth between them, and `.github/workflows/release.yml`
   fails the release on purpose if they (or the tag) disagree.
2. Add a section to `CHANGELOG.md` for the new version.
3. Commit, push, confirm CI is green.
4. Tag and push: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
5. `gh release create vX.Y.Z --notes-file <(sed -n '/## \[X.Y.Z\]/,/## \[/p' CHANGELOG.md | head -n -1)`
   (or just paste that version's CHANGELOG section into the release notes
   by hand). Publishing the release triggers `release.yml`, which builds,
   checks, and publishes to PyPI via Trusted Publishing (OIDC) — no API
   token is stored anywhere in this repo.
6. Once PyPI shows the new version, sanity-check it in a clean venv:
   `pip install palimpsest-translate==X.Y.Z && palimpsest --version`.

## Beyond that

Open an issue before a large PR, keep changes scoped to one concern, and
prefer extending an existing module over introducing a new abstraction
layer. If you're touching `pdf.layout`, `pdf.render`, or `text.protect`,
read the relevant section of `docs/design/` first — several behaviors that
look like they could be simplified are there because of a specific,
documented regression.
