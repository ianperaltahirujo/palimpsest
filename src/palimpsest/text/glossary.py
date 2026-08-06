"""Domain-scoped glossaries with heading-number-aware lookup.

Why this exists
----------------
Generic machine translation is unreliable for domain terminology: it
renders "Cantidad" as "Amount" (a money word) in a bill-of-quantities
context where it means "Quantity", because the general sense is more
common in whatever the translator was trained on. An exact-match
glossary, curated per document domain (legal/corporate boilerplate vs.
IFRS financial-statement captions vs. construction-budget line items),
takes priority over MT for exactly the strings it lists and falls through
to MT for everything else. Domains are complementary rather than merged
into one undifferentiated list on purpose: a real-estate/legal corpus and
an audited-financial-statement corpus want different, non-overlapping
vocabularies, and keeping them separate lets a caller select only the
domains relevant to what it's translating.

Documents number their sections ("2.26 Reconocimiento de ingresos"), and a
glossary entry for the bare heading ("Reconocimiento de ingresos") would
otherwise never match because the number is part of the extracted text.
`Glossary.lookup()` peels a leading heading number, re-consults the
glossary on the remainder, and re-attaches the number afterward -- closing
a real gap in an earlier version of this pipeline, which peeled list
markers and legal ordinals before translation but never re-entered the
glossary on what was left.
"""

from __future__ import annotations

import logging
import re
import tomllib
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

HEADNUM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?\.?)\s+(.*)$")

_BUNDLED_ANCHOR = "palimpsest.text"
_BUNDLED_SUBPATH = ("glossaries", "es-en")


def _bundled_dir():
    root = resources.files(_BUNDLED_ANCHOR)
    for part in _BUNDLED_SUBPATH:
        root = root.joinpath(part)
    return root


def bundled_domain_path(name: str) -> Path | None:
    """Path to a packaged domain glossary (e.g. "legal"), or None if no
    such bundled domain exists."""
    candidate = _bundled_dir().joinpath(f"{name}.toml")
    return Path(str(candidate)) if candidate.is_file() else None


def available_domains() -> tuple[str, ...]:
    root = _bundled_dir()
    if not root.is_dir():
        return ()
    return tuple(sorted(p.stem for p in root.iterdir() if p.name.endswith(".toml")))


class Glossary:
    def __init__(self, terms: dict[str, str] | None = None):
        self.terms: dict[str, str] = dict(terms or {})

    @classmethod
    def load(cls, domains: Iterable[str] = (), extra: Iterable[Path] = ()) -> Glossary:
        """Merge bundled domains (by name, in the given order) and then
        extra user-supplied TOML files (by path, in the given order).
        Later sources win on key collisions; every collision is logged so
        an unintentional override is visible rather than silent."""
        merged: dict[str, str] = {}

        def _merge_from(path: Path, source: str) -> None:
            data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in data.get("terms", {}).items():
                if k in merged and merged[k] != v:
                    log.warning(
                        "glossary collision on %r: %s overrides %r with %r",
                        k, source, merged[k], v,
                    )
                merged[k] = v

        for name in domains:
            path = bundled_domain_path(name)
            if path is None:
                raise ValueError(
                    f"unknown glossary domain {name!r}; available: {available_domains()}"
                )
            _merge_from(path, f"domain {name!r}")

        for path in extra:
            _merge_from(Path(path), str(path))

        return cls(merged)

    def lookup(self, text: str) -> str | None:
        """Exact match, then heading-number-aware fallback. Returns None
        (never the input text) when nothing matches, so callers can tell
        "glossary has an answer" from "glossary has nothing to say"."""
        if text in self.terms:
            return self.terms[text]
        m = HEADNUM_RE.match(text)
        if not m:
            return None
        number, rest = m.group(1), m.group(2).strip()
        hit = self.terms.get(rest)
        return f"{number} {hit}" if hit is not None else None

    def __contains__(self, text: str) -> bool:
        return self.lookup(text) is not None

    def __len__(self) -> int:
        return len(self.terms)
