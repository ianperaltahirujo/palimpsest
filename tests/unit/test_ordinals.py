from palimpsest.text import ordinals
from palimpsest.text.protect import strip_accents


def test_generates_1_through_30():
    assert set(ordinals.ORDINALS) == set(range(1, 31))


def test_decimo_cuarto_is_fourteenth_not_tenth_plus_room():
    """Regression: a table that stops short of 14 matches the shorter
    'DECIMO' prefix alone and leaves 'CUARTO' (which also means 'room') to
    be machine-translated on its own, producing 'TENTH ROOM.' instead of
    'FOURTEENTH.'."""
    en, remainder = ordinals.match("DÉCIMO CUARTO.", strip_accents)
    assert en == "FOURTEENTH"
    assert remainder == "."


def test_longest_match_wins_over_shorter_prefix():
    en, remainder = ordinals.match("DECIMO.", strip_accents)
    assert en == "TENTH"
    assert remainder == "."


def test_first_through_ninth():
    for n in range(1, 10):
        sp, en = ordinals.ORDINALS[n]
        got_en, remainder = ordinals.match(f"{sp}.", strip_accents)
        assert got_en == en
        assert remainder == "."


def test_twenty_first_uses_hyphenated_english_form():
    sp, en = ordinals.ORDINALS[21]
    assert en == "TWENTY-FIRST"
    got_en, _ = ordinals.match(sp + ".", strip_accents)
    assert got_en == en


def test_no_match_returns_none_and_original_text():
    en, remainder = ordinals.match("CONSIDERANDO:", strip_accents)
    assert en is None
    assert remainder == "CONSIDERANDO:"


def test_match_requires_boundary_punctuation_or_space():
    """'CUARTOX' must not match 'CUARTO' -- the ordinal has to be a whole
    word, not merely a prefix of a longer one."""
    en, remainder = ordinals.match("CUARTOX", strip_accents)
    assert en is None
    assert remainder == "CUARTOX"


def test_heading_re_matches_ordinal_at_line_start():
    assert ordinals.HEADING_RE.match("PRIMERO. El presente contrato...")
    # Case-insensitive but NOT accent-insensitive (HEADING_RE is applied to
    # raw extracted text, unlike `match()` which accepts a strip_accents_fn
    # for exactly this reason) -- the unaccented spelling matches:
    assert ordinals.HEADING_RE.match("decimo cuarto: adicionalmente...")


def test_heading_re_does_not_match_mid_sentence():
    assert ordinals.HEADING_RE.match("no es primero.") is None
