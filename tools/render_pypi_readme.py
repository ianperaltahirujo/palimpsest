"""Generate README.pypi.md: README.md with every relative link/image made absolute.

Why this exists
----------------
README.md is written for GitHub, which resolves a relative link/image
against the repo automatically -- and, empirically, gives a plain
same-repo `<img>` zero background, while an image loaded from ANY
absolute URL (raw.githubusercontent.com or a third-party CDN, camo-proxied
or not -- both were tested) gets wrapped in GitHub's own
`js-gh-image-fallback` styling, a visible background box. So README.md
must stay relative for a clean GitHub render.

PyPI's readme_renderer has no repo to resolve a relative path against at
all -- confirmed against the live published project page: every relative
image and cross-file link (LICENSE, NOTICE, CONTRIBUTING.md, the
docs/design/ postmortems, etc.) rendered broken, either a broken-image
icon or plain unlinked text.

There is no single markup that satisfies both platforms, so this script
produces a second, PyPI-only file instead. pyproject.toml's `readme`
field points at the generated file, not README.md.

Usage
-----
    python tools/render_pypi_readme.py           # (re)writes README.pypi.md
    python tools/render_pypi_readme.py --check    # exits 1 if it's stale (CI)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "README.md"
GENERATED = ROOT / "README.pypi.md"

REPO = "ianperaltahirujo/palimpsest"
BLOB_BASE = f"https://github.com/{REPO}/blob/main/"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/"

# A relative target: no scheme, and not a same-page #anchor (those work
# identically on both renderers, since both generate heading ids).
_RELATIVE = r"(?!https?://|#)[^\s\"'()]+"
_IMG_SRC = re.compile(rf'(<img\b[^>]*\bsrc=")({_RELATIVE})(")')
_A_HREF = re.compile(rf'(<a\b[^>]*\bhref=")({_RELATIVE})(")')
_MD_LINK = re.compile(rf'(\]\()({_RELATIVE})(\))')


def _is_image_path(path: str) -> bool:
    return path.rsplit(".", 1)[-1].lower() in {"png", "gif", "jpg", "jpeg", "svg", "webp"}


def render(markdown: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix, path, suffix = match.groups()
        base = RAW_BASE if _is_image_path(path) else BLOB_BASE
        return f"{prefix}{base}{path}{suffix}"

    markdown = _IMG_SRC.sub(replace, markdown)
    markdown = _A_HREF.sub(replace, markdown)
    markdown = _MD_LINK.sub(replace, markdown)
    return markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="exit 1 if README.pypi.md is stale relative to README.md, without writing",
    )
    args = parser.parse_args()

    rendered = render(SOURCE.read_text(encoding="utf-8"))

    if args.check:
        current = GENERATED.read_text(encoding="utf-8") if GENERATED.is_file() else None
        if current != rendered:
            print(
                "error: README.pypi.md is out of date -- run `python tools/render_pypi_readme.py`"
                " and commit the result",
                file=sys.stderr,
            )
            return 1
        print("README.pypi.md is up to date")
        return 0

    GENERATED.write_text(rendered, encoding="utf-8")
    print(f"wrote {GENERATED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
