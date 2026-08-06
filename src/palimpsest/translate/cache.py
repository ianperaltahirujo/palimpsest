"""An honest, namespaced translation cache.

The defect this exists to prevent
------------------------------------
A cache that stores `{source: translation}` and nothing else cannot
distinguish "this failed to translate" from "this translated to exactly
itself" from "this translated successfully" -- so a failed machine
translation call can end up cached as though the untouched source text
WERE the translation, and nothing downstream can tell the difference.
Every entry here carries an explicit status instead:

    {"en": "...", "status": "ok"}          translated
    {"en": null,  "status": "failed"}      backend call errored; retried
    {"en": "...", "status": "identical"}   backend returned the input unchanged
    {"en": null,  "status": "refused"}     backend declined to answer (e.g. an
                                            LLM refusal) -- distinct from "failed"
                                            because it isn't a transient error,
                                            but never used as output either

`status != "ok"` entries are never used as output and are retried on the
next run. `pending()` reports them so a document is never declared
finished while any unit is still untranslated.

Why namespaced
-----------------
A cache keyed only on the source string cannot tell one backend's output
from another's. Switching from Google to an LLM backend (or changing
glossary/entity configuration, which changes what a "correct" translation
looks like) would otherwise silently serve the OLD backend's cached
output as if it were the new one's -- exactly the "a failure masquerades
as a result" class of bug this module exists to prevent in the first
place, just one layer up. Each cache file can hold multiple namespaces
side by side (see `compute_namespace`); only the currently active
namespace is read from or written to, and switching back to a
previously-used configuration finds its cache exactly as it left it
rather than needing to re-translate.

A cache file with no `namespaces` wrapper at all is a legacy flat file
(from a version of this pipeline with no namespacing concept, or the
original `{source: translation}` shape with no status either). It is
migrated in memory into the `LEGACY_NAMESPACE` bucket on load -- readable
and preserved, but never silently treated as belonging to whatever
namespace happens to be active now.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

LEGACY_NAMESPACE = "legacy/unnamespaced"


def compute_namespace(
    backend_name: str,
    model: str | None,
    source_lang: str,
    target_lang: str,
    glossary_terms: Mapping[str, str] | None = None,
    entities: Iterable[str] = (),
    post_rules: Iterable[tuple[str, str]] = (),
) -> str:
    """A short, deterministic identifier for "this exact translation
    configuration". Two Translator instances with the same backend,
    model, language pair, glossary, entity list, and post-processing
    rules compute the same namespace and share a cache; any difference in
    any of those produces a different one."""
    payload = {
        "backend": backend_name,
        "model": model,
        "source": source_lang,
        "target": target_lang,
        "glossary": sorted(dict(glossary_terms or {}).items()),
        "entities": sorted(entities),
        "post_rules": [list(r) for r in post_rules],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{backend_name}:{digest}"


def _normalize_entries(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Accept both the current {"en":, "status":} shape and a legacy flat
    {source: translation} shape, migrating the latter in memory. A flat
    entry whose value equals its key is re-classified as "identical"
    rather than trusted -- it's exactly what a naive `results.append(s)`
    failure-handling bug would have produced."""
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[k] = v
        else:
            status = "identical" if (v or "").strip() == k.strip() else "ok"
            out[k] = {"en": v, "status": status}
    return out


class Cache:
    def __init__(self, path: str | Path, namespace: str):
        self.path = Path(path)
        self.namespace = namespace
        self._namespaces: dict[str, dict[str, dict[str, Any]]] = {}
        self._dirty = False
        self.load()

    @property
    def data(self) -> dict[str, dict[str, Any]]:
        """The active namespace's entries. Mutating this dict (as `put`
        and `retry_pending` do) marks the cache dirty implicitly through
        the methods that use it -- direct mutation by callers should go
        through `put`."""
        return self._namespaces.setdefault(self.namespace, {})

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict) and isinstance(raw.get("namespaces"), dict):
            for ns, entries in raw["namespaces"].items():
                if isinstance(entries, dict):
                    self._namespaces[ns] = _normalize_entries(entries)
        elif isinstance(raw, dict):
            self._namespaces[LEGACY_NAMESPACE] = _normalize_entries(raw)

    def save(self) -> None:
        if not self._dirty:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"namespaces": self._namespaces}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._dirty = False

    def get_ok(self, key: str) -> str | None:
        entry = self.data.get(key)
        if entry and entry.get("status") == "ok" and entry.get("en"):
            return entry["en"]
        return None

    def put(self, key: str, en: str | None, status: str) -> None:
        self.data[key] = {"en": en, "status": status}
        self._dirty = True

    def pending(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.data.items() if v.get("status") != "ok"}
