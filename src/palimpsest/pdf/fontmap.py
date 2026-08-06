"""Resolve a PDF font name to a REAL font file with full glyph coverage.

Why this exists
----------------
The naive fix -- pull the embedded font buffer back out of the PDF with
`doc.extract_font()` and re-embed it -- does NOT work for documents
produced by Word, and it is worth recording why so nobody tries it again:

  * Word SUBSETS embedded fonts down to only the glyphs the source text
    actually used. A Spanish-only document's `ABCDEE+Baskerville Old
    Face` can have no `W` glyph at all -- but the English translation
    certainly needs one.
  * Several subsets carry a (3,0) symbol cmap with codes remapped into
    the 0xF000 private-use range, so a plain unicode lookup misses nearly
    every ASCII character even though the outlines are present.

So instead this resolves by NAME to the full font installed on the
machine (or bundled with palimpsest as a last-resort fallback), which has
complete glyph coverage. A substitution is always recorded in
`FontResolver.substitutions` so a QA report can show exactly where
typography could not be matched, rather than silently degrading.

Why a class, not module functions
----------------------------------
An earlier version of this kept the font index, alias cache, and
substitution log as module-level globals. The alias cache was correctly
scoped (keyed on `id(document), page number, family, style`, so a page
never gets served an alias installed for a different document). The
substitution log was not: `SUBSTITUTIONS` was a single dict that
accumulated across an entire batch run with nothing to reset it between
documents, so a per-document "here's what typography couldn't be
matched" report was silently reporting every substitution from every
document processed so far in the run, not just the current file's.
`FontResolver` is instantiated once per document (or once per process if
a caller genuinely wants cross-document alias caching, via
`reset_alias_cache()` between documents) so `.substitutions` always
answers "what did resolving fonts for THIS instance's calls actually
need" -- accurate per-document reporting becomes the only thing possible,
not an opt-in a caller has to remember.
"""

from __future__ import annotations

import os
import platform
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import fitz

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
# No trailing \b: names like 'Calibri-BoldItalic' run the two style words
# together, so a word boundary after 'Bold' never matches.
_BOLD_RE = re.compile(r"(bold|black|heavy|semibold|demibold)|(?<![a-z])bd(?![a-z])", re.I)
_ITAL_RE = re.compile(r"(italic|oblique)|(?<![a-z])it(?![a-z])", re.I)
# Trailing PostScript cruft: TimesNewRomanPS-BoldMT -> Times New Roman
_PS_SUFFIX_RE = re.compile(r"(PSMT|PS-?|MT|Std|Pro)$", re.I)

# Families deliberately never used to render text -- icon/dingbat faces
# whose "text" is decorative, not linguistic.
SYMBOL_FAMILIES = {"wingdings", "wingdings 2", "wingdings 3", "webdings", "symbol", "marlett"}

# Names that are not real typefaces -- placeholders emitted by OCR tooling.
_PLACEHOLDER_FAMILIES = {"glyph less font", "glyphlessfont", "glyphless"}

_SERIF_HINTS = (
    "times", "georgia", "garamond", "book", "baskerville", "cambria",
    "roman", "serif", "antiqua", "bookman", "palatino", "century schoolbook",
)
_MONO_HINTS = ("courier", "consolas", "mono")

_BUNDLED_ANCHOR = "palimpsest"
_BUNDLED_SUBPATH = ("assets", "fonts")

# A same-class substitute family name to try in the SYSTEM font index when
# the document's own family can't be found there. These are common
# Windows/Office faces; on a machine without them (e.g. Linux CI), the
# resolver falls through further to the bundled fallback tier below.
_SYSTEM_FALLBACK = {"mono": "courier new", "serif": "georgia", "sans": "arial"}

# Same-class substitute to try in the BUNDLED fallback tier (see
# bundled_font_dir()). Deliberately generic family names, not tied to any
# specific font product, so whatever ships in assets/fonts/ can be swapped
# without changing this mapping.
_BUNDLED_FALLBACK = {
    "mono": "monospace fallback", "serif": "serif fallback", "sans": "sans fallback",
}


def _font_class(family: str) -> str:
    f = family.lower()
    if any(h in f for h in _MONO_HINTS):
        return "mono"
    if any(h in f for h in _SERIF_HINTS):
        return "serif"
    return "sans"


def platform_font_dirs() -> tuple[Path, ...]:
    """System font directories for the current OS. Best-effort: a
    directory that doesn't exist is simply not scanned, so this never
    raises on a minimal container image with no fonts installed at all."""
    system = platform.system()
    if system == "Windows":
        dirs = [Path(r"C:\Windows\Fonts")]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return tuple(dirs)
    if system == "Darwin":
        return (
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        )
    # Linux and anything else POSIX-like.
    return (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / ".fonts",
    )


def bundled_font_dir() -> Path | None:
    """Directory of fonts packaged with palimpsest itself, used as the
    fallback tier below the system font index. None if the package was
    installed without them (e.g. a minimal build) or none are present."""
    root = resources.files(_BUNDLED_ANCHOR)
    for part in _BUNDLED_SUBPATH:
        root = root.joinpath(part)
    path = Path(str(root))
    return path if path.is_dir() else None


def _read_name_table(path: Path) -> tuple[str | None, bool, bool]:
    """Return (family, bold, italic) for a TrueType/OpenType file.

    Family comes from the `name` table (nameID 1), preferring the English
    Windows record (platform 3, language 0x409).

    Style deliberately does NOT come from the subfamily string (nameID
    2): on a machine with localized font metadata those records can be in
    another language (e.g. "Gras" instead of "Bold"), so an English
    keyword match silently fails and every weight collapses onto
    whichever file happens to sort first. Style is read instead from the
    `head` table's macStyle bitfield (bit 0 = bold, bit 1 = italic),
    which is numeric and language-independent.

    Parsed directly rather than via a font library so this needs nothing
    beyond the stdlib.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None, False, False
    if len(data) < 12:
        return None, False, False
    offset = 0
    if data[:4] == b"ttcf":  # font collection -- read the first face
        if len(data) < 16:
            return None, False, False
        offset = struct.unpack(">I", data[12:16])[0]
        if offset + 12 > len(data):
            return None, False, False
    try:
        num_tables = struct.unpack(">H", data[offset + 4:offset + 6])[0]
    except struct.error:
        return None, False, False

    tables: dict[bytes, tuple[int, int]] = {}
    for i in range(num_tables):
        rec = offset + 12 + i * 16
        if rec + 16 > len(data):
            return None, False, False
        tag = data[rec:rec + 4]
        off, ln = struct.unpack(">II", data[rec + 8:rec + 16])
        tables[tag] = (off, ln)

    bold = italic = False
    if b"head" in tables:
        hoff = tables[b"head"][0]
        if hoff + 46 <= len(data):
            mac_style = struct.unpack(">H", data[hoff + 44:hoff + 46])[0]
            bold = bool(mac_style & 0x01)
            italic = bool(mac_style & 0x02)

    if b"name" not in tables:
        return None, bold, italic
    name_off = tables[b"name"][0]
    if name_off + 6 > len(data):
        return None, bold, italic
    count, str_off = struct.unpack(">HH", data[name_off + 2:name_off + 6])
    family = None
    family_rank = -1
    for i in range(count):
        rec = name_off + 6 + i * 12
        if rec + 12 > len(data):
            break
        pid, eid, lid, nid, ln, off = struct.unpack(">HHHHHH", data[rec:rec + 12])
        if nid != 1:
            continue
        start = name_off + str_off + off
        raw = data[start:start + ln]
        if not raw:
            continue
        try:
            val = raw.decode("utf-16-be" if pid == 3 else "latin-1", "ignore").strip()
        except Exception:
            continue
        if not val:
            continue
        # Prefer English-Windows, then any Windows, then anything at all.
        rank = 2 if (pid == 3 and lid == 0x409) else 1 if pid == 3 else 0
        if rank > family_rank:
            family, family_rank = val, rank
    return family, bold, italic


def _normalise(s: str) -> str:
    s = s.replace("-", " ").replace("_", " ").replace(",", " ")
    # CamelCase -> spaced ('NotoSans' -> 'Noto Sans', 'TimesNewRoman' -> 'Times New Roman')
    if " " not in s.strip():
        s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def parse_pdf_fontname(fontname: str | None) -> tuple[list[str], bool, bool]:
    """Split a PDF font name into (candidate_families, bold, italic).

    Two candidates are returned, in priority order, because a style
    keyword in the name is ambiguous: it may describe the weight OR be
    part of the family name itself. 'Britannic Bold' and 'Arial Rounded
    MT Bold' are whole family names -- stripping 'Bold' off them yields
    families that do not exist and silently falls back to a substitute.
    So the full name is tried first and the style-stripped form only as a
    fallback.

        'ABCDEE+Book Antiqua'          -> (['book antiqua'], False, False)
        'Arial,Bold'                   -> (['arial'], True, False)
        'ABCDEE+Britannic Bold'        -> (['britannic bold', 'britannic'], True, False)
        'ABCDEE+Arial Rounded MT Bold' -> (['arial rounded mt bold',
                                             'arial rounded mt'], True, False)
        'TimesNewRomanPS-BoldMT'       -> (['times new roman ps boldmt',
                                             'times new roman'], True, False)
        'Calibri-BoldItalic'           -> (['calibri bolditalic', 'calibri'], True, True)
    """
    name = _SUBSET_RE.sub("", fontname or "")
    bold = bool(_BOLD_RE.search(name))
    ital = bool(_ITAL_RE.search(name))

    full = _normalise(name)

    base = re.split(r"[,]", name)[0]
    base = re.sub(
        r"-(Bold|Italic|Oblique|BoldItalic|BoldOblique|Regular|Roman|Light|Medium)+.*$",
        "", base, flags=re.I,
    )
    base = _PS_SUFFIX_RE.sub("", base).strip()
    base = _BOLD_RE.sub("", base)
    base = _ITAL_RE.sub("", base)
    stripped = _normalise(base)

    candidates = [c for c in (full, stripped) if c]
    seen: set[str] = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
    return candidates, bold, ital


def base14(bold: bool, italic: bool, serif: bool = False) -> str:
    if serif:
        return "tibi" if (bold and italic) else "tibo" if bold else "tiit" if italic else "tiro"
    return "hebi" if (bold and italic) else "hebo" if bold else "heit" if italic else "helv"


@dataclass
class FontResolver:
    """Resolves PDF font names to real font files and installs them on
    pages, with per-instance caching. Instantiate one per document (the
    common case) or share one across a whole run if cross-document
    caching is genuinely wanted -- either way, `substitutions` reports
    exactly what this instance resolved, not some other run's history."""

    extra_dirs: Sequence[Path] = ()
    use_bundled_fallback: bool = True

    substitutions: dict[str, str] = field(default_factory=dict, init=False)
    _index: dict[str, dict[tuple[bool, bool], Path]] = field(default_factory=dict, init=False)
    _bundled_index: dict[str, dict[tuple[bool, bool], Path]] = field(
        default_factory=dict, init=False
    )
    _alias_cache: dict[tuple, str] = field(default_factory=dict, init=False)
    _built: bool = field(default=False, init=False)

    def _scan_dir(self, directory: Path, into: dict) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.tt*")) + sorted(directory.glob("*.otf")):
            family, bold, ital = _read_name_table(path)
            if not family:
                continue
            into.setdefault(family.strip().lower(), {}).setdefault((bold, ital), path)

    def _build_index(self) -> None:
        if self._built:
            return
        for d in platform_font_dirs():
            self._scan_dir(d, self._index)
        for d in self.extra_dirs:
            self._scan_dir(Path(d), self._index)
        if self.use_bundled_fallback:
            bundled = bundled_font_dir()
            if bundled is not None:
                self._scan_dir(bundled, self._bundled_index)
        self._built = True

    def resolve(
        self,
        fontname: str | None,
        bold: bool | None = None,
        italic: bool | None = None,
        default_family: str | None = None,
    ) -> tuple[Path | None, str, bool, bool, bool]:
        """Return (path, family, bold, italic, substituted) for a PDF font
        name.

        `bold`/`italic` override whatever the name implies -- needed on
        scanned pages, where an OCR text layer names every font
        `GlyphLessFont` and encodes no weight at all; the real weight is
        measured from page pixels (see `pdf.inkstyle`) and passed in here.

        `default_family` supplies the face to use when the name carries
        no usable family -- again the OCR case, where `GlyphLessFont` is
        a placeholder rather than a real typeface.

        `path` is None only when nothing at all could be resolved, in
        which case the caller should fall back to a base-14 name.
        """
        self._build_index()
        candidates, name_bold, name_ital = parse_pdf_fontname(fontname)
        if default_family and (not candidates or candidates[0] in _PLACEHOLDER_FAMILIES):
            candidates = [default_family.lower()]
        bold = name_bold if bold is None else bold
        ital = name_ital if italic is None else italic
        if not candidates:
            candidates = ["arial"]
        family = candidates[-1]

        def pick(index: dict, fam: str, b: bool, i: bool) -> Path | None:
            styles = index.get(fam)
            if not styles:
                return None
            # exact style, then relax italic, then relax bold, then anything
            for key in ((b, i), (b, False), (False, i), (False, False)):
                if key in styles:
                    return styles[key]
            return next(iter(styles.values()))

        for cand in candidates:
            path = pick(self._index, cand, bold, ital)
            if path:
                return path, cand, bold, ital, False

        klass = _font_class(family)
        sub = _SYSTEM_FALLBACK[klass]
        path = pick(self._index, sub, bold, ital)
        if path:
            self.substitutions[family] = sub
            return path, sub, bold, ital, True

        bundled_sub = _BUNDLED_FALLBACK[klass]
        path = pick(self._bundled_index, bundled_sub, bold, ital)
        if path:
            self.substitutions[family] = f"{bundled_sub} (bundled)"
            return path, bundled_sub, bold, ital, True

        self.substitutions[family] = "<base14>"
        return None, family, bold, ital, True

    def alias_for(
        self,
        page: fitz.Page,
        fontname: str | None,
        bold: bool | None = None,
        italic: bool | None = None,
        default_family: str | None = None,
    ) -> str:
        """Install the resolved font on `page` and return the alias to
        render with.

        Aliases are cached per (document, page, family, style) so a font
        is embedded once per page rather than once per paragraph. Keyed
        per PAGE, not per document: a PDF font lives in the page's own
        resource dictionary, so `insert_font` has to run once for every
        page that uses the face.
        """
        path, family, bold_r, ital_r, _ = self.resolve(fontname, bold, italic, default_family)
        doc = page.parent
        key = (id(doc), page.number, family, bold_r, ital_r)
        if key in self._alias_cache:
            return self._alias_cache[key]
        if path is None:
            alias = base14(bold_r, ital_r, serif=any(h in family for h in _SERIF_HINTS))
            self._alias_cache[key] = alias
            return alias
        safe = re.sub(r"[^A-Za-z0-9]", "", family)[:20] or "F"
        alias = f"{safe}{'B' if bold_r else ''}{'I' if ital_r else ''}"
        try:
            page.insert_font(fontname=alias, fontfile=str(path))
        except Exception:
            alias = base14(bold_r, ital_r, serif=any(h in family for h in _SERIF_HINTS))
        self._alias_cache[key] = alias
        return alias

    def font_object(
        self,
        fontname: str | None,
        bold: bool | None = None,
        italic: bool | None = None,
        default_family: str | None = None,
    ) -> fitz.Font:
        """A fitz.Font for measurement (same face the page will actually render)."""
        path, family, bold_r, ital_r, _ = self.resolve(fontname, bold, italic, default_family)
        if path:
            try:
                return fitz.Font(fontfile=str(path))
            except Exception:
                pass
        serif = any(h in family for h in _SERIF_HINTS)
        return fitz.Font(fontname=base14(bold_r, ital_r, serif=serif))

    def reset_alias_cache(self) -> None:
        """Call between documents if reusing one FontResolver across a
        batch run and page numbers can repeat across different
        fitz.Document objects."""
        self._alias_cache.clear()
