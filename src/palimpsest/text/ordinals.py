"""Spanish legal ordinals ("PRIMERO", "DECIMO CUARTO", ...) mapped to their
English equivalents, plus a regex to recognise them as clause headings.

Why this exists
----------------
Legal documents in this language pair number clauses with spelled-out
ordinals: `PRIMERO.`, `SEGUNDO.`, ..., `DECIMO CUARTO.`. Two failures come
from this if it's left to generic machine translation:

1. Sent to MT, an ordinal is just another Spanish word with an unrelated
   literal sense. `CUARTO.` (fourth) also means "room" as a noun, so
   `CUARTO. TRANSFERENCIA.` comes back "ROOM. TRANSFER." A table that only
   covers ordinals up to some fixed size makes this worse, not better: if
   it stops at `DECIMO TERCERO` (13th), then `DECIMO CUARTO` (14th) falls
   through by matching the shorter `DECIMO` prefix alone, translating
   "TENTH", and leaving "CUARTO." to be machine-translated into "ROOM."
   right after it. That failure mode is why this table is generated
   programmatically for 1-30 rather than hand-listed to whatever length
   happened to cover the first document tested against -- a longer
   document (a multi-article trust deed, say) will keep working instead of
   silently degrading past whatever number the list stopped at.

2. Nothing else marks an ordinal heading as the start of a new paragraph,
   so a clause heading with no distinguishing bold or size (plain-weight
   body text, as in some scanned permits) gets welded onto whatever
   preceded it -- e.g. a list item's wrapped continuation -- and gets
   translated as one run-on paragraph. `HEADING_RE` exists to give the
   layout extractor a paragraph-break signal that doesn't depend on style.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_SP_UNITS = [
    "PRIMERO", "SEGUNDO", "TERCERO", "CUARTO", "QUINTO",
    "SEXTO", "SEPTIMO", "OCTAVO", "NOVENO",
]
_EN_UNITS = [
    "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH",
    "SIXTH", "SEVENTH", "EIGHTH", "NINTH",
]
_EN_TEENS = [
    "TENTH", "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH",
    "FIFTEENTH", "SIXTEENTH", "SEVENTEENTH", "EIGHTEENTH", "NINETEENTH",
]

# ORDINALS[n] = (Spanish ordinal word(s), unaccented upper-case, English word)
ORDINALS: dict[int, tuple[str, str]] = {}
for _n in range(1, 10):
    ORDINALS[_n] = (_SP_UNITS[_n - 1], _EN_UNITS[_n - 1])
ORDINALS[10] = ("DECIMO", "TENTH")
for _n in range(11, 20):
    ORDINALS[_n] = (f"DECIMO {_SP_UNITS[_n - 11]}", _EN_TEENS[_n - 10])
ORDINALS[20] = ("VIGESIMO", "TWENTIETH")
for _n in range(21, 30):
    ORDINALS[_n] = (f"VIGESIMO {_SP_UNITS[_n - 21]}", f"TWENTY-{_EN_UNITS[_n - 21]}")
ORDINALS[30] = ("TRIGESIMO", "THIRTIETH")

# Longest Spanish form first, so "DECIMO CUARTO" is tried before "DECIMO".
_BY_LENGTH = sorted(ORDINALS.values(), key=lambda pair: -len(pair[0]))

# Matches a line that OPENS with one of these ordinals followed by the
# punctuation legal headings use ('.', ',', ':' or a following space), so it
# can be used as a hard paragraph-break signal even when a heading carries no
# bold or size distinction from the body text around it.
HEADING_RE = re.compile(
    "^(?:" + "|".join(re.escape(sp) for sp, _ in _BY_LENGTH) + r")[.,:\s]",
    re.IGNORECASE,
)


def match(text: str, strip_accents_fn: Callable[[str], str]) -> tuple[str | None, str]:
    """If `text` opens with a Spanish ordinal, return (english, remainder).

    Else (None, text). `strip_accents_fn` should be
    `palimpsest.text.protect.strip_accents`.
    """
    flat = strip_accents_fn(text).upper()
    for sp, en in _BY_LENGTH:
        if flat.startswith(sp):
            tail = text[len(sp):]
            if tail[:1] in (".", ",", ":", " ", ")", ""):
                return en, tail
    return None, text
