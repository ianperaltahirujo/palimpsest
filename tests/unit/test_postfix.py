from palimpsest.text.postfix import DATE_RULES, apply


def test_dd_of_month_of_yyyy():
    assert apply("14 of January of 2026", DATE_RULES) == "January 14, 2026"


def test_dd_of_month_comma_yyyy():
    assert apply("14 of January, 2026", DATE_RULES) == "January 14, 2026"


def test_month_dd_of_yyyy():
    assert apply("January 14 of 2026", DATE_RULES) == "January 14, 2026"


def test_dd_month_yyyy_no_of():
    assert apply("14 January 2026", DATE_RULES) == "January 14, 2026"


def test_month_dd_yyyy_no_comma():
    """A date form an earlier rule set lacked: no 'of', no comma at all."""
    assert apply("January 14 2026", DATE_RULES) == "January 14, 2026"


def test_dd_of_month_no_year():
    assert apply("the meeting on 14 of January was held", DATE_RULES) == (
        "the meeting on January 14 was held"
    )


def test_the_month_dd():
    assert apply("filed on the January 14", DATE_RULES) == "filed on January 14"


def test_collapses_double_comma():
    """Merging two rule sets can leave 'X, , Y' where each rule
    independently inserted a comma; this cleans it up."""
    assert apply("Santo Domingo,  , Dominican Republic", DATE_RULES) == (
        "Santo Domingo, Dominican Republic"
    )


def test_santo_domingo_misparsed_as_sunday_is_corrected():
    """MT parses the place name 'Santo Domingo' as if 'Domingo' were the
    weekday 'Sunday' -- a real machine-translation failure, not a
    hypothetical one."""
    assert apply("located in Sunday Domingo", DATE_RULES) == "located in Santo Domingo"
    assert apply("Holy Sunday, Dominican Republic", DATE_RULES) == (
        "Santo Domingo, Dominican Republic"
    )


def test_strips_zero_width_characters():
    text = "Grupo​ Meridian"
    assert apply(text, []) == "Grupo Meridian"


def test_none_passes_through():
    assert apply(None, DATE_RULES) is None


def test_apply_with_no_rules_is_identity_modulo_zero_width():
    assert apply("plain text", []) == "plain text"
