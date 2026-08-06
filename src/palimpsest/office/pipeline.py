"""Translate an Office file (.xlsx/.docx/.pptx) by OOXML surgery.

No separate `EntityGuard` call here, unlike `pdf.pipeline`: `Translator`
already applies its guard internally on every `translate()` call (it was
constructed with the document's entity list), so `lookup()` below gets
that protection for free. `pdf.pipeline` checks the guard itself first
only so it can report a paragraph as "skipped" rather than "translated"
-- a bookkeeping distinction this module doesn't make.
"""

from __future__ import annotations

from pathlib import Path

from palimpsest.config.model import Config
from palimpsest.office import ooxml
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import Backend
from palimpsest.translate.registry import build_translator


def translate_office_document(
    src: Path,
    out: Path,
    rel: str,
    backend: Backend,
    entities: tuple[str, ...],
    glossary: Glossary,
    post_rules: tuple[tuple[str, str], ...],
    config: Config,
) -> dict:
    tr = build_translator(rel, config, backend, entities, glossary, post_rules)

    strings = ooxml.collect_strings(str(src))
    names = [n for n in ooxml.sheet_names(str(src)) if ooxml._translatable(n)]
    tr.warm(strings + names)

    failures: list[str] = []

    def lookup(s: str) -> str | None:
        en, status = tr.translate(s)
        if status != "ok":
            failures.append(s)
            return None  # leave the original in place rather than blank it
        return en

    out.parent.mkdir(parents=True, exist_ok=True)
    stats = ooxml.translate_office(str(src), str(out), lookup)
    tr.cache.save()

    diff = ooxml.verify(str(src), str(out))
    return {"stats": stats, "diff": diff, "failures": failures}
