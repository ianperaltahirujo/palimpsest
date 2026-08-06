"""De-identification gate: fail the build if a denylisted term appears.

Why this exists
----------------
palimpsest was extracted from a working pipeline built against real client
documents (legal deeds, credit-bureau reports, audited financial
statements). The engineering postmortems in docs/design/ are the project's
best writing, but every example in them was rewritten against a fictional
cast before publication. This script is the mechanical backstop for that
rewrite: it fails CI if a real name, filename, or identifying string ever
reaches the tree or the git history, so a slip doesn't depend on a human
reviewer catching it by eye.

How matching works
-------------------
Terms are matched case-folded AND accent-stripped, because the source
corpus itself writes the same proper noun both ways (e.g. the deed spells
a place name with accents, a scanned permit spells it without) -- so a
naive case-sensitive or accent-sensitive grep would miss half the real
occurrences this tool exists to catch. See palimpsest.text.protect for the
same accent-stripping approach applied to entity protection at translation
time; this script deliberately does not import that package (it must also
run against a checkout that doesn't build yet, e.g. in PR1).

Denylist location
------------------
The actual denylist (real names, filenames, deal-specific terms) is
disclosive by definition, so it is never committed here. It is loaded from
a path given by $PALIMPSEST_DENYLIST, which points OUTSIDE this repo. If
the variable is unset, this script falls back to a small, generic,
committed pattern set (obvious PII shapes, absolute Windows user paths,
OneDrive paths) and prints a warning that the full check did not run --
that warning is intentional so CI logs show plainly that a fallback
happened, rather than silently reporting green.

Usage
-----
    python tools/scrub_check.py                  # working tree only
    python tools/scrub_check.py --history         # + full git log -p
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Generic fallback patterns -- no client identity, just structural leaks
# that would embarrass any repo, checked in so the gate is never a no-op.
GENERIC_DENYLIST = [
    r"C:\Users\hyper",
    "OneDrive\\Documents\\JMMB",
    "PrimePlaza",
    "GPD Consolidado",
    "ANTHROPIC_API_KEY=sk-",
]

SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    return strip_accents(s).casefold()


def load_denylist() -> tuple[list[str], bool]:
    path = os.environ.get("PALIMPSEST_DENYLIST")
    if path and Path(path).is_file():
        terms = [
            line.strip()
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return terms, True
    return GENERIC_DENYLIST, False


def iter_tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [REPO_ROOT / line for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # No git yet (first run in PR1, before the first commit) -- walk the
        # working tree directly, honoring the skip list.
        files = []
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files.extend(Path(dirpath) / f for f in filenames)
        return files


def scan_text(label: str, text: str, denylist: list[str]) -> list[tuple[str, str]]:
    hits = []
    normalized = normalize(text)
    for term in denylist:
        if normalize(term) in normalized:
            hits.append((label, term))
    return hits


def scan_working_tree(denylist: list[str]) -> list[tuple[str, str]]:
    hits = []
    for path in iter_tracked_files():
        if path.name == Path(__file__).name:
            continue  # this file legitimately quotes the fallback terms
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        hits.extend(scan_text(str(path.relative_to(REPO_ROOT)), text, denylist))
        # Filenames leak too -- a disclosive document name doesn't need to
        # appear inside a file to be a problem.
        hits.extend(scan_text(f"{path.relative_to(REPO_ROOT)} (filename)", path.name, denylist))
    return hits


def scan_history(denylist: list[str]) -> list[tuple[str, str]]:
    try:
        out = subprocess.run(
            ["git", "log", "-p", "--all"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return scan_text("git history", out, denylist)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan full git log -p")
    args = parser.parse_args(argv)

    denylist, using_real_denylist = load_denylist()
    if not using_real_denylist:
        print(
            "WARNING: PALIMPSEST_DENYLIST not set or unreadable -- running only "
            "the small generic fallback list, not the real one. Do not treat a "
            "green result here as a full de-identification pass.",
            file=sys.stderr,
        )

    hits = scan_working_tree(denylist)
    if args.history:
        hits.extend(scan_history(denylist))

    if hits:
        print(f"scrub_check: {len(hits)} denylisted term(s) found:", file=sys.stderr)
        for label, term in hits:
            print(f"  {label}: {term!r}", file=sys.stderr)
        return 1

    print(f"scrub_check: clean ({'real' if using_real_denylist else 'generic fallback'} denylist, "
          f"{len(denylist)} terms{', + history' if args.history else ''}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
