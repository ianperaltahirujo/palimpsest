import re

import pytest

from palimpsest.text.protect import (
    EntityGuard,
    build_protect_re,
    protect,
    protected_word_fragments,
    restore,
    strip_accents,
)

FICTIONAL_ENTITIES = [
    "Grupo Meridian",
    "Grupo Aurora, SRL.",
    "Grupo Peñasco",
    "Banco Litoral",
    "Andrés Carreño",
    "Santo Domingo Este",
    "Ciudad Juan Bosch",
]


# -- strip_accents --------------------------------------------------------

def test_strip_accents_removes_diacritics_only():
    assert strip_accents("Peñasco Núñez") == "Penasco Nunez"
    assert strip_accents("ABC123") == "ABC123"


# -- protect / restore round-trip -----------------------------------------

def test_protect_restore_round_trip():
    protect_re = build_protect_re(FICTIONAL_ENTITIES)
    text = "Grupo Meridian pagó RD$50,000 en Santo Domingo Este."
    placeheld, tokens = protect(text, protect_re)
    assert "[[" in placeheld
    assert restore(placeheld, tokens) == text


def test_restore_tolerates_spaced_brackets():
    """MT sometimes inserts stray whitespace inside the placeholder
    brackets ('[[ 3 ]]' instead of '[[3]]')."""
    tokens = ["Grupo Meridian", "RD$50,000"]
    text = "[[ 0 ]] pagó [[1]]."
    assert restore(text, tokens) == "Grupo Meridian pagó RD$50,000."


def test_restore_out_of_range_index_is_left_untouched():
    assert restore("see [[9]]", []) == "see [[9]]"


def test_restore_none_returns_none():
    assert restore(None, []) is None


def test_protect_is_case_insensitive_and_preserves_source_casing():
    """A real regression: source text shouts proper nouns in table cells
    and all-caps headings ('SANTO DOMINGO ESTE') while the entity list
    holds mixed-case spellings. Case-insensitive matching must still
    round-trip the ALL-CAPS form verbatim, not the entity list's casing."""
    protect_re = build_protect_re(FICTIONAL_ENTITIES)
    text = "PROPIEDAD UBICADA EN SANTO DOMINGO ESTE, CIUDAD JUAN BOSCH."
    placeheld, tokens = protect(text, protect_re)
    assert restore(placeheld, tokens) == text
    assert "SANTO DOMINGO ESTE" in tokens


def test_protect_matches_accent_stripped_variant():
    """Documents in this language pair spell the same proper noun both
    ways -- accented in a typed deed, unaccented in a scanned permit."""
    protect_re = build_protect_re(["Ciudad Juan Bosch", "Avenida Ecológica"])
    text = "domicilio en la AVENIDA ECOLOGICA, cerca de Ciudad Juan Bosch"
    placeheld, tokens = protect(text, protect_re)
    assert restore(placeheld, tokens) == text


def test_protect_covers_currency_and_bare_numbers():
    protect_re = build_protect_re([])
    text = "El monto es RD$1,250.50 mas US$400 y 37 unidades."
    placeheld, tokens = protect(text, protect_re)
    assert restore(placeheld, tokens) == text
    # Every amount/number is placeholdered, i.e. absent from the text an
    # MT backend would actually see.
    for raw in ("RD$1,250.50", "US$400", "37"):
        assert raw not in placeheld
    assert set(tokens) == {"RD$1,250.50", "US$400", "37"}


def test_short_entity_does_not_match_inside_an_unrelated_word():
    """A real regression found translating a securities-sector filing: the
    protected abbreviation 'CCI' (a real broker-dealer ticker) matched as
    a bare substring inside ordinary Spanish words that happen to contain
    the same three letters -- 'contraCCIon' (contracción), 'reduCCIon'
    (reducción) -- corrupting them into 'against[[N]]' / 'net[[N]]' after
    the surrounding word got machine-translated around the placeholder.
    Spanish '-cción' is a common suffix, so this wasn't a one-off."""
    protect_re = build_protect_re(["CCI"])
    text = "una contracción neta y una reducción similar, con CCI presente"
    placeheld, tokens = protect(text, protect_re)
    assert "contracción" in placeheld
    assert "reducción" in placeheld
    assert tokens == ["CCI"]


def test_entity_ending_in_punctuation_still_matches_at_sentence_end():
    """The boundary fix above must not regress entities that themselves
    end in punctuation (a real entry: 'Grupo Aurora, SRL.') -- a naive
    `\\b` word-boundary anchor would never match here, since `\\b` needs a
    word-character transition and a trailing '.' followed by a space
    never provides one."""
    protect_re = build_protect_re(["Grupo Aurora, SRL."])
    text = "La empresa contratante es Grupo Aurora, SRL. y firmo el acuerdo."
    placeheld, tokens = protect(text, protect_re)
    assert tokens == ["Grupo Aurora, SRL."]
    assert restore(placeheld, tokens) == text


# -- protected_word_fragments ----------------------------------------------

def test_fragments_only_from_multiword_entities():
    frags = protected_word_fragments(["Grupo Aurora", "Meridian", "Banco Litoral"])
    assert "AURORA" in frags
    assert "GRUPO" in frags
    assert "LITORAL" in frags
    assert "BANCO" in frags
    # Single-word entries are excluded: already fully protected by the
    # substring regex, and appearing alone isn't evidence of truncation.
    assert "MERIDIAN" not in frags


def test_fragments_ignore_short_words():
    frags = protected_word_fragments(["De La O"])
    assert "DE" not in frags  # below the 3-char floor
    assert "LA" not in frags


# -- EntityGuard: is_wholly_protected --------------------------------------

def test_wholly_protected_standalone_company_line():
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert guard.is_wholly_protected("Grupo Aurora, SRL.")


def test_not_wholly_protected_when_entity_merely_mentioned():
    """The core distinction this guard exists for: a paragraph that
    MENTIONS a protected entity in passing must still be translated."""
    guard = EntityGuard(FICTIONAL_ENTITIES)
    text = (
        "En nuestra opinión, los estados financieros de Grupo Meridian "
        "presentan razonablemente..."
    )
    assert not guard.is_wholly_protected(text)


def test_wholly_protected_matches_case_and_accent_insensitively():
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert guard.is_wholly_protected("GRUPO PENASCO")


def test_wholly_protected_empty_text_is_false():
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert not guard.is_wholly_protected("   ")


def test_not_protected_when_no_entity_present():
    """An unrelated fragment must not look 'protected' just because it has
    little content -- only text that actually names something protected
    can be skipped."""
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert not guard.is_wholly_protected("de 2025")


# -- EntityGuard: is_name_fragment ------------------------------------------

def test_name_fragment_single_word_of_multiword_entity():
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert guard.is_name_fragment("GRUPO")
    assert guard.is_name_fragment("Meridian")  # second word of "Grupo Meridian"


def test_name_fragment_false_for_unrelated_word():
    guard = EntityGuard(FICTIONAL_ENTITIES)
    assert not guard.is_name_fragment("PROPIEDAD")


# -- EntityGuard: single funnel point (the GRUPO -> CLUSTER regression) ----
#
# The pipeline this project was extracted from had three real bypasses of
# entity protection, each found by tracing actual call stacks rather than
# by code inspection: a label-split path that translated an isolated
# sub-fragment directly, a prefix-peeling path (list markers / legal
# ordinals) whose remainder skipped the check, and a batch pre-translation
# pass that built its work list from cache/glossary membership only. All
# three let a bare 'GRUPO' (a fragment of a longer protected company name)
# reach the translation backend and come back as 'CLUSTER'. These tests
# don't exercise Translator (that lands in PR5 with the translation core)
# -- they pin the guard itself, which is what every one of those call
# sites should have consulted and didn't.


class FakeBackend:
    """Stands in for a real MT backend: translates 'GRUPO' -> 'CLUSTER'
    and echoes everything else, so any call site that skips the guard is
    caught red-handed rather than producing a plausible-looking result."""

    def __init__(self):
        self.calls: list[str] = []

    def translate(self, text: str) -> str:
        self.calls.append(text)
        return "CLUSTER" if text.strip().upper() == "GRUPO" else text


@pytest.mark.parametrize(
    "fragment",
    [
        "GRUPO",
        "grupo",
        " Grupo ",
        "GRUPO.",
        "GRUPO,",
    ],
)
def test_guard_catches_bare_grupo_in_any_casing_or_punctuation(fragment):
    guard = EntityGuard(["Grupo Meridian", "Grupo Aurora, SRL.", "Grupo Peñasco"])
    assert guard.skip(fragment), (
        f"{fragment!r} should be recognised as a name fragment and never "
        "reach a translation backend -- sending it through is exactly the "
        "GRUPO -> CLUSTER failure class this guard exists to prevent."
    )


def test_a_caller_that_correctly_uses_the_guard_never_calls_the_backend():
    guard = EntityGuard(["Grupo Meridian"])
    backend = FakeBackend()

    def translate_paragraph(text: str) -> str:
        if guard.skip(text):
            return text
        return backend.translate(text)

    assert translate_paragraph("GRUPO") == "GRUPO"
    assert backend.calls == []


def test_a_caller_that_bypasses_the_guard_reproduces_the_regression():
    """Documents, via a deliberately-wrong caller, exactly what goes wrong
    when a call site skips EntityGuard -- this is the shape of bug the
    three real bypasses had, kept here so the failure mode stays visible
    even though the guard itself now prevents it everywhere it's used."""
    backend = FakeBackend()

    def buggy_translate_with_prefix(text: str) -> str:
        # Peels a leading list marker, then translates the remainder
        # WITHOUT re-checking the guard -- this is bypass #2 from the
        # source pipeline (translate_with_prefix's post-peel remainder).
        m = re.match(r"^(\d+\.)\s*(.*)$", text)
        if not m:
            return backend.translate(text)
        num, rest = m.groups()
        return f"{num} {backend.translate(rest)}"

    assert buggy_translate_with_prefix("2. GRUPO") == "2. CLUSTER"
    assert "GRUPO" in backend.calls
