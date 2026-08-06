import tomllib

import pytest

from palimpsest.text.glossary import Glossary, available_domains, bundled_domain_path


def test_bundled_domains_include_legal_ifrs_construction():
    domains = available_domains()
    assert {"legal", "ifrs", "construction"} <= set(domains)


def test_bundled_domain_path_resolves_a_real_file():
    path = bundled_domain_path("legal")
    assert path is not None
    assert path.is_file()


def test_bundled_domain_path_none_for_unknown_domain():
    assert bundled_domain_path("nonexistent-domain") is None


def test_every_bundled_domain_file_is_valid_toml_with_terms_table():
    for name in available_domains():
        path = bundled_domain_path(name)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "terms" in data
        assert isinstance(data["terms"], dict)
        assert len(data["terms"]) > 0


def test_load_single_domain_exact_match():
    glossary = Glossary.load(domains=["legal"])
    assert glossary.lookup("Fideicomiso") == "Trust"


def test_load_unknown_domain_raises():
    with pytest.raises(ValueError):
        Glossary.load(domains=["not-a-real-domain"])


def test_lookup_returns_none_not_input_text_when_missing():
    glossary = Glossary.load(domains=["legal"])
    assert glossary.lookup("this phrase is not in the glossary") is None


def test_heading_number_lookup_peels_and_reattaches_number():
    """The v1 merge this module exists to bring in: '2.26 Reconocimiento
    de ingresos' should hit the glossary via the bare heading even though
    the numbered form itself isn't a literal key."""
    glossary = Glossary.load(domains=["ifrs"])
    assert glossary.lookup("Reconocimiento de ingresos") == "Revenue recognition"
    assert glossary.lookup("2.26 Reconocimiento de ingresos") == "2.26 Revenue recognition"
    assert glossary.lookup("14. Reconocimiento de ingresos") == "14. Revenue recognition"
    assert glossary.lookup("3.1. Reconocimiento de ingresos") == "3.1. Revenue recognition"


def test_heading_number_lookup_returns_none_if_remainder_not_in_glossary():
    glossary = Glossary.load(domains=["ifrs"])
    assert glossary.lookup("2.26 Some unrelated heading text") is None


def test_domains_are_complementary_not_overlapping_by_default():
    """legal.toml and construction.toml should not define conflicting
    terms -- they're meant to be safely combined."""
    legal = Glossary.load(domains=["legal"])
    construction = Glossary.load(domains=["construction"])
    shared_keys = set(legal.terms) & set(construction.terms)
    for key in shared_keys:
        assert legal.terms[key] == construction.terms[key]


def test_construction_domain_disambiguates_cantidad_as_quantity():
    """The documented reason this domain exists: generic MT renders
    'Cantidad' as 'Amount' in a bill-of-quantities context where it means
    'Quantity'."""
    glossary = Glossary.load(domains=["construction"])
    assert glossary.lookup("Cantidad") == "Quantity"


def test_later_domain_wins_on_collision(tmp_path):
    a = tmp_path / "a.toml"
    a.write_text('[terms]\n"Total" = "Sum"\n', encoding="utf-8")
    b = tmp_path / "b.toml"
    b.write_text('[terms]\n"Total" = "Total"\n', encoding="utf-8")

    glossary_ab = Glossary.load(domains=[], extra=[a, b])
    assert glossary_ab.lookup("Total") == "Total"

    glossary_ba = Glossary.load(domains=[], extra=[b, a])
    assert glossary_ba.lookup("Total") == "Sum"


def test_contains_and_len():
    glossary = Glossary.load(domains=["legal"])
    assert "Fideicomiso" in glossary
    assert "not a real term" not in glossary
    assert len(glossary) > 0


def test_ifrs_glossary_has_no_duplicate_key_corruption():
    """Regression for a real authoring hazard: the source dict this
    domain was transcribed from had several keys repeated verbatim across
    sections (harmless in Python, a hard TOML parse error otherwise) --
    confirm the shipped file parses and the repeated entries agree with
    what the source pipeline used."""
    glossary = Glossary.load(domains=["ifrs"])
    assert glossary.lookup("Inversiones en asociadas") == "Investments in associates"
    assert glossary.lookup("Gastos pagados por anticipado") == "Prepaid expenses"
