"""Cross-platform relative-path handling.

Why this exists
----------------
Document maps and cache keys need a canonical, OS-independent identity for
"the same relative document path" so a map authored on Windows works
unmodified on Linux or macOS, and so the same document produces the same
cache key regardless of which OS translated it.

Two concrete failure modes this fixes:

1. A path key built with `os.path.join` on Windows embeds literal
   backslashes (`"Financial statements\\Deed.pdf"`). On POSIX, `\\` is not
   a path separator -- it's a literal character in a filename -- so the
   same key resolves to a completely different (nonexistent) path.
2. macOS normalizes filenames to NFD on the filesystem layer, while
   Windows and most authoring tools produce NFC. A path key containing
   accented characters (common in this language pair -- 'ó', 'ñ', 'í')
   compares unequal across the two even when a human would call them "the
   same filename".
"""

from __future__ import annotations

import unicodedata
from pathlib import Path, PurePosixPath


def norm_rel(s: str) -> PurePosixPath:
    """Canonicalize a relative path key: forward slashes, no leading or
    trailing slash, NFC-normalised. Use this on every document-map key,
    cache key, and report key so the same document maps to the same key
    everywhere regardless of the authoring OS."""
    posix = s.replace("\\", "/")
    normalized = unicodedata.normalize("NFC", posix)
    return PurePosixPath(normalized.strip("/"))


def to_fs(root: Path, rel: PurePosixPath | str) -> Path:
    """Resolve a canonical relative key against a filesystem root, using
    the OS's own path-joining rules (so the result is a real, usable path
    on whatever platform this runs on)."""
    if isinstance(rel, str):
        rel = norm_rel(rel)
    return root.joinpath(*rel.parts)


def cache_key(rel: PurePosixPath, max_len: int = 90) -> str:
    """Filesystem-safe cache filename stem for a canonical relative path.
    Takes the already-normalized form (i.e. the output of `norm_rel`) so
    callers can't accidentally derive a key from a raw, un-normalized OS
    path string."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(rel))
    return slug[-max_len:]
