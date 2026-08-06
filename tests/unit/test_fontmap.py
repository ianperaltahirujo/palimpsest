from pathlib import Path

from palimpsest.pdf.fontmap import (
    FontResolver,
    base14,
    bundled_font_dir,
    parse_pdf_fontname,
    platform_font_dirs,
)

# -- parse_pdf_fontname: pure string logic, no I/O --------------------------

def test_strips_subset_prefix():
    candidates, bold, ital = parse_pdf_fontname("ABCDEE+Book Antiqua")
    assert candidates == ["book antiqua"]
    assert not bold and not ital


def test_comma_style_suffix():
    candidates, bold, ital = parse_pdf_fontname("Arial,Bold")
    assert "arial" in candidates
    assert bold and not ital


def test_whole_family_name_containing_bold_tried_first():
    """'Britannic Bold' is a whole family name, not 'Britannic' + weight
    keyword -- the full name must be the FIRST candidate, since stripping
    'Bold' off it yields a family that doesn't exist."""
    candidates, bold, ital = parse_pdf_fontname("ABCDEE+Britannic Bold")
    assert candidates[0] == "britannic bold"
    assert candidates[1] == "britannic"
    assert bold and not ital


def test_arial_rounded_mt_bold_whole_name_first():
    candidates, bold, ital = parse_pdf_fontname("ABCDEE+Arial Rounded MT Bold")
    assert candidates[0] == "arial rounded mt bold"
    # No hyphen before the style word (unlike 'TimesNewRomanPS-BoldMT'), so
    # only the bold keyword itself is stripped from the fallback candidate.
    assert candidates[1] == "arial rounded mt"
    assert bold


def test_postscript_suffix_stripped():
    candidates, bold, ital = parse_pdf_fontname("TimesNewRomanPS-BoldMT")
    assert "times new roman" in candidates
    assert bold and not ital


def test_calibri_bolditalic_hyphenated():
    candidates, bold, ital = parse_pdf_fontname("Calibri-BoldItalic")
    assert "calibri" in candidates
    assert bold and ital


def test_camelcase_family_gets_spaced():
    candidates, _bold, _ital = parse_pdf_fontname("TimesNewRoman")
    assert "times new roman" in candidates


def test_none_fontname_does_not_raise():
    candidates, bold, ital = parse_pdf_fontname(None)
    assert candidates == []
    assert not bold and not ital


def test_candidates_are_deduplicated_preserving_order():
    # A name whose full and stripped forms normalise identically should
    # yield exactly one candidate, not two.
    candidates, _bold, _ital = parse_pdf_fontname("Arial")
    assert candidates == ["arial"]


# -- base14 -------------------------------------------------------------

def test_base14_sans_variants():
    assert base14(False, False) == "helv"
    assert base14(True, False) == "hebo"
    assert base14(False, True) == "heit"
    assert base14(True, True) == "hebi"


def test_base14_serif_variants():
    assert base14(False, False, serif=True) == "tiro"
    assert base14(True, False, serif=True) == "tibo"
    assert base14(False, True, serif=True) == "tiit"
    assert base14(True, True, serif=True) == "tibi"


# -- platform_font_dirs / bundled_font_dir: no I/O failures ---------------

def test_platform_font_dirs_returns_paths():
    dirs = platform_font_dirs()
    assert len(dirs) > 0
    assert all(isinstance(d, Path) for d in dirs)


def test_bundled_font_dir_does_not_raise_when_empty():
    # assets/fonts/ currently ships no font files (see its README) --
    # this must return a real, existing directory (or None), never raise.
    result = bundled_font_dir()
    assert result is None or result.is_dir()


# -- FontResolver.resolve: pre-populated index, no real font files needed --

def _resolver_with_fake_index(index: dict, bundled: dict | None = None) -> FontResolver:
    """Bypass the real filesystem scan entirely -- the resolution LOGIC
    (candidate matching, fallback ordering, substitution recording) is
    what's worth testing; the TTF-table-parsing step that populates the
    index is a separate, mechanical concern."""
    resolver = FontResolver(use_bundled_fallback=bundled is not None)
    resolver._built = True
    resolver._index.update(index)
    if bundled:
        resolver._bundled_index.update(bundled)
    return resolver


def test_resolve_exact_family_and_style_match():
    resolver = _resolver_with_fake_index({"calibri": {(False, False): Path("calibri.ttf")}})
    path, family, bold, ital, substituted = resolver.resolve("Calibri")
    assert path == Path("calibri.ttf")
    assert family == "calibri"
    assert not substituted


def test_resolve_relaxes_italic_before_bold():
    resolver = _resolver_with_fake_index({
        "calibri": {(True, False): Path("calibri-bold.ttf"), (False, False): Path("calibri.ttf")}
    })
    # Asking for (bold, italic) with no italic variant present should
    # fall back to (bold, not-italic) before giving up on bold entirely.
    path, _family, _bold, _ital, substituted = resolver.resolve("Calibri", bold=True, italic=True)
    assert path == Path("calibri-bold.ttf")
    assert not substituted


def test_resolve_falls_back_to_system_same_class_substitute():
    resolver = _resolver_with_fake_index({"arial": {(False, False): Path("arial.ttf")}})
    path, family, _bold, _ital, substituted = resolver.resolve("SomeUnknownSansFace")
    assert path == Path("arial.ttf")
    assert family == "arial"
    assert substituted
    assert resolver.substitutions["some unknown sans face"] == "arial"


def test_resolve_falls_back_to_bundled_when_system_substitute_absent():
    resolver = _resolver_with_fake_index(
        index={},
        bundled={"sans fallback": {(False, False): Path("bundled-sans.ttf")}},
    )
    path, family, _bold, _ital, substituted = resolver.resolve("SomeUnknownSansFace")
    assert path == Path("bundled-sans.ttf")
    assert family == "sans fallback"
    assert substituted
    assert "bundled" in resolver.substitutions["some unknown sans face"]


def test_resolve_returns_none_path_when_nothing_found_at_all():
    resolver = _resolver_with_fake_index({})
    path, _family, _bold, _ital, substituted = resolver.resolve("SomeUnknownSansFace")
    assert path is None
    assert substituted
    assert resolver.substitutions["some unknown sans face"] == "<base14>"


def test_resolve_serif_hint_prefers_serif_fallback():
    resolver = _resolver_with_fake_index({"georgia": {(False, False): Path("georgia.ttf")}})
    path, family, _bold, _ital, substituted = resolver.resolve("Baskerville Old Face")
    assert path == Path("georgia.ttf")
    assert family == "georgia"
    assert substituted


def test_resolve_mono_hint_prefers_courier_new():
    resolver = _resolver_with_fake_index({"courier new": {(False, False): Path("cour.ttf")}})
    path, family, _bold, _ital, _substituted = resolver.resolve("Consolas")
    assert path == Path("cour.ttf")
    assert family == "courier new"


def test_resolve_default_family_used_for_placeholder_ocr_font():
    """An OCR text layer names every span with a placeholder font --
    'GlyphLessFont' -- which carries no usable family. default_family
    must be substituted in that case."""
    resolver = _resolver_with_fake_index({"calibri": {(False, False): Path("calibri.ttf")}})
    path, family, _bold, _ital, _substituted = resolver.resolve(
        "GlyphLessFont", default_family="Calibri"
    )
    assert path == Path("calibri.ttf")
    assert family == "calibri"


def test_resolve_explicit_bold_italic_override_name_derived_values():
    resolver = _resolver_with_fake_index({"calibri": {(True, True): Path("calibri-bi.ttf")}})
    # The name itself implies neither bold nor italic; explicit args win.
    path, _family, bold, ital, _substituted = resolver.resolve("Calibri", bold=True, italic=True)
    assert path == Path("calibri-bi.ttf")
    assert bold and ital


def test_font_object_falls_back_to_base14_with_empty_index():
    resolver = _resolver_with_fake_index({})
    font = resolver.font_object("SomeUnknownFace")
    assert font is not None  # fitz.Font(fontname=base14(...)) never raises
