"""Corpus-wide cache health audits.

Why this exists
----------------
A real corpus this pipeline was run against surfaced a specific failure
class after the initial pilot run, not during it: a bare fragment of a
multi-word protected company name (its first word alone) reached the
translation backend and came back mistranslated -- "GRUPO" became
"CLUSTER" -- because the fragment never made it into the extracted text
as part of the full phrase (see `text.protect.protected_word_fragments`
for the two confirmed causes). The fix was verified at the time by a
corpus-wide scan: every cache entry whose key is a bare constituent word
of a protected entity, and whose cached value differs from the key, run
to zero across several full-corpus re-runs. That scan was ad hoc and no
longer exists as a script.

`poisoned_fragment_entries` reconstructs it as a real, maintained,
importable function -- run against a fixture cache in CI (see
tests/unit/test_audit.py) to guard the regression itself, and available
to run against a user's own real cache via `palimpsest audit cache`
(wired up in a later stage of this project).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from palimpsest.text.protect import protected_word_fragments, strip_accents


@dataclass(frozen=True)
class PoisonedEntry:
    cache_file: Path
    namespace: str
    source: str
    cached_value: str


def _iter_namespaced_entries(raw: dict) -> Iterable[tuple[str, dict]]:
    """Yield (namespace, entries) for every namespace in a cache file,
    tolerating both the current {"namespaces": {...}} shape and a legacy
    flat {source: value} file (reported under namespace "" since it
    predates namespacing entirely)."""
    if isinstance(raw.get("namespaces"), dict):
        yield from raw["namespaces"].items()
    else:
        yield "", raw


def poisoned_fragment_entries(
    cache_dir: Path, entities: Iterable[str]
) -> list[PoisonedEntry]:
    """Every cache entry, across every JSON file in `cache_dir` and every
    namespace within each file, whose key is a bare constituent word of a
    multi-word protected entity and whose cached value differs from the
    key -- i.e. a fragment that reached a translation backend in
    isolation and came back changed. An empty result is the invariant
    this function exists to check; any hit is the GRUPO -> CLUSTER
    failure class recurring and should block a release the same way a
    failing test would.
    """
    fragments = protected_word_fragments(entities)
    hits: list[PoisonedEntry] = []
    for path in sorted(Path(cache_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        for namespace, entries in _iter_namespaced_entries(raw):
            if not isinstance(entries, dict):
                continue
            for key, value in entries.items():
                en = value.get("en") if isinstance(value, dict) else value
                if not isinstance(en, str):
                    continue
                bare = strip_accents(key.strip().strip(".,;:()\"")).upper()
                if bare in fragments and en.strip() != key.strip():
                    hits.append(PoisonedEntry(path, namespace, key, en))
    return hits
