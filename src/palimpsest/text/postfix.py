"""Post-translation text fixups.

Why this exists
----------------
Machine translation of Spanish dates produces several literal variants of
the same underlying meaning that read as bugs if left alone -- "14 of
January of 2026", "January 14 of 2026", "the January 14" -- where the
desired form is "January 14, 2026". These rules run AFTER protected-entity
restoration, so they see real English month names and restored proper
nouns rather than `[[N]]` placeholders.

One rule below exists because of a specific machine-translation failure,
not a general date-formatting problem: MT parsed the place name "Santo
Domingo" as if "Domingo" were the weekday "Sunday" (`domingo` is both a
common Spanish place/given name and the word for "Sunday"), producing
"Sunday Domingo" and, in one observed case, "Holy Sunday" out of "Santo
Domingo". Both are corrected back explicitly rather than guarded against
generically, because the failure is specific enough that a general
"don't translate place names" rule isn't obviously safer or simpler.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

ZERO_WIDTH_RE = re.compile("[​‌‍﻿]")

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)

# The packaged "dates" rule set (selected via [postrules] sets = ["dates"]
# in palimpsest.toml). Curly-quote normalization is deliberately NOT
# included here: an earlier version of this pipeline rewrote curly quotes
# to straight ones because it drew inserted text with a base-14 Helvetica
# font that has no glyph for them. palimpsest embeds real TrueType fonts
# (see palimpsest.pdf.fontmap), which do have the glyph, so typographic
# quotes are preserved rather than flattened.
DATE_RULES: list[tuple[str, str]] = [
    (rf"\b(\d{{1,2}}) of ({_MONTHS}) of (\d{{4}})\b", r"\2 \1, \3"),
    (rf"\b(\d{{1,2}}) of ({_MONTHS}),? (\d{{4}})\b", r"\2 \1, \3"),
    (rf"\b({_MONTHS}) (\d{{1,2}}) of (\d{{4}})\b", r"\1 \2, \3"),
    (rf"\b(\d{{1,2}}) ({_MONTHS}) (\d{{4}})\b", r"\2 \1, \3"),
    (rf"\b({_MONTHS}) (\d{{1,2}}) (\d{{4}})\b", r"\1 \2, \3"),
    (rf"\b(\d{{1,2}}) of ({_MONTHS})\b(?!,)(?!\s+\d)", r"\2 \1"),
    (rf"\bthe ({_MONTHS}) (\d{{1,2}})\b", r"\1 \2"),
    (r",\s*,+", ","),
    # "Santo Domingo" mis-parsed as if "Domingo" were the weekday.
    (r"\bSunday\s+Domingo\b", "Santo Domingo"),
    (r"\bHoly\s+Sunday\b", "Santo Domingo"),
]


def apply(text: str | None, rules: Iterable[tuple[str, str]]) -> str | None:
    """Run `rules` (an iterable of (pattern, replacement)) over `text`,
    after stripping zero-width characters MT sometimes introduces."""
    if text is None:
        return None
    text = ZERO_WIDTH_RE.sub("", text)
    for pattern, replacement in rules:
        text = re.sub(pattern, replacement, text)
    return text
