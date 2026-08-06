from pathlib import Path, PurePosixPath

from palimpsest.core.paths import cache_key, norm_rel, to_fs


def test_backslash_normalizes_to_forward_slash():
    """A map authored on Windows with os.path.join embeds literal
    backslashes -- on POSIX that's a filename character, not a separator,
    so the same key must resolve identically on both."""
    assert norm_rel("Financial statements\\Deed.pdf") == PurePosixPath(
        "Financial statements/Deed.pdf"
    )


def test_forward_slash_path_is_unchanged():
    assert norm_rel("Financial statements/Deed.pdf") == PurePosixPath(
        "Financial statements/Deed.pdf"
    )


def test_strips_leading_and_trailing_slashes():
    assert norm_rel("/a/b/") == PurePosixPath("a/b")


def test_nfd_and_nfc_spellings_of_accented_names_are_equal():
    """macOS filesystems normalize to NFD; Windows/most authoring tools
    produce NFC. The same human-readable filename must compare equal."""
    nfc = "Información societaria.pdf"
    nfd = "Informacio\u0301n societaria.pdf"  # 'o' + combining acute accent
    assert nfc != nfd  # sanity: they really are different byte sequences
    assert norm_rel(nfc) == norm_rel(nfd)


def test_to_fs_joins_using_native_separators():
    root = Path("C:/corpus") if Path("C:/corpus").drive else Path("/corpus")
    result = to_fs(root, norm_rel("Financial statements\\Deed.pdf"))
    assert result == root / "Financial statements" / "Deed.pdf"


def test_cache_key_is_filesystem_safe():
    key = cache_key(norm_rel("Información/Consulta crediticia (1).pdf"))
    assert all(c.isalnum() or c == "_" for c in key)


def test_cache_key_truncates_to_max_len_from_the_end():
    long_rel = norm_rel("a/" * 60 + "file.pdf")
    key = cache_key(long_rel, max_len=20)
    assert len(key) == 20


def test_cache_key_deterministic_across_backslash_and_forward_slash():
    a = cache_key(norm_rel("Info\\Deed.pdf"))
    b = cache_key(norm_rel("Info/Deed.pdf"))
    assert a == b
