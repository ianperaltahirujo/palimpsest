"""Entity protection: keep proper nouns and amounts verbatim across MT.

Why this exists
----------------
Generic machine translation "translates" things that must not change:
company names, personal names, and place names get rendered as if they
were ordinary prose. On documents that shout proper nouns in table cells
and all-caps headings, this produces real damage -- a source reading
`SANTO DOMINGO ESTE` and `CIUDAD JUAN BOSCH` came back "HOLY DOMINGO THIS"
and "JUAN BOSCH CITY" from a naive case-sensitive protection scheme, because
the protected-entity list held the mixed-case spellings (`Santo Domingo
Este`) and the document used the shouted all-caps form. `build_protect_re`
matches case-insensitively for exactly this reason, and captures the
matched text verbatim so the source's own capitalization survives either
way regardless of which case it was authored in.

Documents in this language pair also routinely spell the same proper noun
two ways -- accented in a typed deed, unaccented in a scanned permit
(`Avenida Ecológica` vs. `AVENIDA ECOLOGICA`) -- and only one spelling
tends to make it into a hand-curated entity list. Accent-stripped variants
are generated automatically so both spellings are covered from one entry.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_TOKEN_RE = re.compile(r"\[\[(\d+)\]\]")

_NAME_CHARS = r"A-Za-zÀ-ÖØ-öø-ÿ"


def build_protect_re(entities: Iterable[str]) -> re.Pattern[str]:
    """Regex matching entities (plus bare numbers/currency amounts) that
    must survive translation verbatim. Case-insensitive; matches both the
    accented and accent-stripped spelling of every entry."""
    variants = set()
    for s in entities:
        variants.add(s)
        variants.add(strip_accents(s))
    parts = [re.escape(s) for s in sorted(variants, key=len, reverse=True)]
    parts += [r"RD\$[\d.,]+", r"US\$[\d.,]+", r"\$[\d.,]+", r"\b\d[\d.,]*\b"]
    return re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)


def protect(text: str, protect_re: re.Pattern[str]) -> tuple[str, list[str]]:
    """Replace every protect_re match with a `[[N]]` placeholder. Returns
    the placeholdered text and the list of original matches, in order."""
    tokens: list[str] = []

    def repl(m: re.Match[str]) -> str:
        tokens.append(m.group(0))
        return f"[[{len(tokens) - 1}]]"

    return protect_re.sub(repl, text), tokens


def restore(text: str | None, tokens: list[str]) -> str | None:
    """Inverse of protect(). Tolerant of MT inserting stray whitespace
    inside the brackets (`[[ 3 ]]`) and of an out-of-range index, which is
    left untouched rather than raising -- a dropped or mangled placeholder
    is a translation-quality signal for the caller, not a crash."""
    if text is None:
        return None

    def repl(m: re.Match[str]) -> str:
        i = int(m.group(1))
        return tokens[i] if 0 <= i < len(tokens) else m.group(0)

    return re.sub(r"\[\[\s*(\d+)\s*\]\]", repl, text)


def all_tokens_restored(text: str | None) -> bool:
    return not _TOKEN_RE.search(text or "")


def protected_word_fragments(entities: Iterable[str]) -> set[str]:
    """Individual words drawn from multi-word protected entities only.

    A paragraph that is nothing but ONE of these words, alone, is a
    fragment of a longer protected name -- never legitimate freestanding
    prose in a corpus built around specifically named companies and
    people -- and must not reach MT at all, not even with the rest of the
    phrase protected via `protect_re`, because there IS no rest: the
    phrase never made it into the extracted text as a unit. Two confirmed
    causes produce this: OCR reporting a different bbox-derived size per
    word within one heading (so the words end up in separate style runs
    and get extracted as separate paragraphs), and OCR simply never
    recognising part of a stylised letterhead logo -- e.g. a scanned
    letterhead reading "GRUPO PEÑASCO" where OCR read "GRUPO" on five
    separate pages but never recognised "PEÑASCO" in any of them, because
    it rendered as decorative typography rather than plain text.

    Single-word protected entries (e.g. a bare `Meridian`) are excluded on
    purpose: those are already fully protected by the substring regex, and
    their appearing alone is not evidence that anything was truncated.
    """
    words = set()
    for phrase in entities:
        parts = phrase.split()
        if len(parts) < 2:
            continue
        for w in parts:
            w = strip_accents(w).upper().strip(".,;:()\"")
            if len(w) >= 3:
                words.add(w)
    return words


class EntityGuard:
    """Single funnel point for every entity-protection decision.

    Earlier versions of this logic lived at each call site that might hand
    text to the translation backend -- and kept getting bypassed as new
    call sites were added, because each one had to remember to re-check.
    Three such bypasses were found in the pipeline this project was
    extracted from, each discovered only by tracing actual call stacks,
    not by inspecting the code for obviously-missing checks: a label-split
    path that translated an isolated sub-fragment directly; a
    prefix-peeling path (list markers, legal ordinals) whose remainder went
    straight to the backend; and a batch pre-translation pass that built
    its work list from cache/glossary membership only, without consulting
    this guard at all. The fix was architectural, not another patch at a
    fourth call site: callers must route every unit through one
    `EntityGuard` instance, and nothing downstream re-implements any part
    of this decision.
    """

    def __init__(self, entities: Iterable[str]):
        self.entities = tuple(entities)
        self.protect_re = build_protect_re(self.entities)
        self.fragments = protected_word_fragments(self.entities)
        self._whole_substrings = {strip_accents(s).casefold() for s in self.entities if s.strip()}

    def is_name_fragment(self, text: str) -> bool:
        """A paragraph that is ONE constituent word of a multi-word entity
        (see `protected_word_fragments`)."""
        bare = strip_accents(text.strip().strip(".,;:()\"")).upper()
        return bare in self.fragments

    def is_wholly_protected(self, text: str) -> bool:
        """True only when the entire text is nothing but protected
        entity name(s) -- e.g. a standalone company-name line on its own.

        A paragraph that merely MENTIONS a protected entity in passing
        must still be translated (the entity itself is protected
        separately, at the MT layer, via placeholder substitution):
        disqualifying the whole unit here would leave prose like "In our
        opinion, the accompanying financial statements of Grupo Meridian,
        S.A.S. present fairly..." completely untranslated just because it
        names the company.
        """
        t = text.strip()
        if not t:
            return False
        residual = strip_accents(t).casefold()
        found = False
        for sub in self._whole_substrings:
            if sub in residual:
                found = True
                residual = residual.replace(sub, " ")
        if not found:
            return False
        residual_words = re.findall(f"[{_NAME_CHARS}]{{3,}}", residual)
        return len(residual_words) == 0

    def skip(self, text: str) -> bool:
        """True if this text unit must never reach the translation backend
        at all -- the caller should pass it through unchanged instead."""
        return self.is_name_fragment(text) or self.is_wholly_protected(text)
