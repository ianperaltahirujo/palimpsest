# v1 postmortem

palimpsest was extracted from the second generation of a Spanish→English
document-translation pipeline built for a real legal/financial document
corpus. The first generation rebuilt every document from scratch and lost
logos, fonts, layout, and whole file parts in the process. This is the list
of what was actually wrong with it, and what in this codebase exists
specifically because of each failure. Nothing here is hypothetical --
every item below was found by diffing v1 output against the source and
tracing the bug to its cause.

## Logos and artwork erased

v1's page-clearing step called `page.apply_redactions()` with no arguments.
PyMuPDF's defaults are `images=2` (`PDF_REDACT_IMAGE_PIXELS`, blanks image
pixels under the redaction rectangle) and `graphics=1` (deletes vector line
art covered by it). On a scanned page the *entire page* is one image, so
this punched holes through the scan wherever a text region happened to
overlap a letterhead rule, a seal, or a border.

Fixed in `palimpsest.pdf.clearing`: every redaction call passes
`images=PDF_REDACT_IMAGE_NONE, graphics=PDF_REDACT_LINE_ART_NONE`, and a
scanned page's raster is repainted with a colour sampled from the region
itself (the paper behind the glyphs), not hard white.

## Typography discarded

v1 collapsed every font to base-14 Helvetica or Times. Re-embedding the
*source's own* embedded font doesn't fix this: Word subsets fonts down to
only the glyphs the source text used, so a Spanish-only document's
`ABCDEE+Baskerville Old Face` can have no `W` glyph at all, and several
subsets carry a symbol cmap remapped into the 0xF000 private-use range,
so even a plain-unicode lookup misses nearly every ASCII character.

Fixed in `palimpsest.pdf.fontmap`: fonts are resolved by NAME against the
real font installed on the machine (or a bundled fallback), which has
complete glyph coverage. Every substitution is recorded so a QA pass can
see exactly where typography couldn't be matched, instead of silently
degrading.

## Fonts lost after page one

v1's font-alias cache was keyed per *document*, but a PDF font lives in
each *page's own* resource dictionary -- `insert_font` has to run once for
every page that uses a face. So a font got embedded on page 1 only, and
every later page silently fell back to Helvetica.

Fixed: `FontResolver`'s alias cache is keyed on `(document identity, page
number, family, style)`.

## Ragged, mis-sized text

v1 shrank each translated unit independently against its own box, so one
paragraph could render at several different sizes depending on how each
fragment happened to wrap. Justified source text came out ragged because
nothing reproduced real justification (extra space distributed between
words).

Fixed in `palimpsest.pdf.render`: a whole paragraph is fit and scaled as
one unit, and the source's measured alignment -- including real
justification -- is reproduced.

## Columns merged across a table

v1's paragraph grouping ran across table-column boundaries. A two-column
row reading `Dirección | Municipio` next to `SANTO DOMINGO ESTE` came out
as the single run-on phrase "Municipality Address" -- the column values
were concatenated as if they were one sentence.

Fixed in `palimpsest.pdf.layout.column_bands`, which derives columns from
the block's own line geometry. `page.find_tables()` was tried and
deliberately rejected: on these documents it slices a tall cell into one
sub-cell per text line, which shatters a multi-line paragraph into
per-line fragments -- a worse failure than the one it would fix.

## Failures shipped as translations

On a machine-translation error, v1's error handling did the equivalent of
`results.append(source_text)` -- caching the untranslated Spanish source
as though it were the finished English translation. Nothing downstream
could tell a real translation from a silently-failed one.

Fixed in `palimpsest.translate.cache`: every cache entry carries an
explicit status (`ok` / `failed` / `identical` / `refused`). Anything not
`ok` is retried and never rendered; a paragraph that still fails after
retries is left as the original Spanish and listed in the run report,
rather than silently passed off as translated.

## Spreadsheet parts destroyed

v1 round-tripped `.xlsx` files through openpyxl: load, edit, save. Measured
against real source workbooks, that dropped every `xl/drawings/*` part
(every shape, text box, and image), `xl/metadata`, several sheets'
`.rels`, all `webextensions/*` parts, and `calcChain.xml` -- four to ten
parts per workbook, depending on how much the sheet used beyond plain
cell values.

Fixed in `palimpsest.office.ooxml`: the file is opened as what it actually
is, a zip of XML parts. Only the parts that carry human-readable text are
parsed and rewritten; every other entry is copied through byte-for-byte
with its original compression and timestamp.

## OCR ran in the wrong language

v1's Tesseract install only had the `eng`/`osd` language data on its
default search path; the Spanish model lived somewhere OCR wasn't looking.
Scanned Spanish pages were silently OCR'd as English, producing a text
layer that didn't remotely match the page.

Fixed: `[ocr].tessdata_prefix` and `[ocr].language` are explicit
configuration (`palimpsest.pdf.ocr`), and `ensure_ocr()` fails loudly with
an actionable error when the requested language pack isn't found, instead
of silently OCR'ing in the wrong language.

## OCR inflated file size

`--force-ocr` rasterises every page and rebuilds the PDF from that raster
-- on one real letter-sized scan this took a 659 KB source to 2.26 MB,
needlessly re-encoding an already-clean image. These source scans have no
text layer at all to begin with, so `--skip-text` OCRs every page anyway
while leaving the original scan image untouched.

Fixed: `palimpsest.pdf.ocr` uses `--skip-text` by default
(`[ocr].mode`), never `--force-ocr`.

## Untranslatable tokens sent to MT

A Spanish legal ordinal like `CUARTO.` (fourth) is also the ordinary word
for "room" -- sent to generic MT it came back "ROOM.". A list marker like
`a)` came back "to)", the preposition reading of `a`.

Fixed: `pdf.pipeline.split_prefix` peels a leading list marker and/or
spelled-out legal ordinal off before translation and re-attaches it,
already in English, afterward -- the translator never sees it and cannot
corrupt it. The ordinal table (`text.ordinals`) is *generated*
programmatically for 1st through 30th rather than hand-listed: a hand-list
that stops short silently fails past its last entry. On the real source
that first surfaced this, `DECIMO CUARTO` (14th) fell past a 13-entry
hand-list, matched the shorter `DECIMO` (10th) instead, translated as
"TENTH", and left `CUARTO.` -- "room" -- to be machine-translated on its
own right after it, producing "TENTH ROOM." in the actual output.

See [`protected-entities.md`](protected-entities.md) for a second,
later-discovered failure class in the same family: not mistranslated
ordinals, but protected entity names translated in isolation.
