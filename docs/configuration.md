# Configuration

palimpsest is configured with a `palimpsest.toml` project file, layered on
top of packaged defaults, with two further files for data that must never
be committed.

## Layers

1. **Packaged defaults** (`src/palimpsest/config/defaults.toml`) — ships
   with the package. Thresholds only.
2. **Project config** (`palimpsest.toml`) — safe to commit. Start from
   [`examples/palimpsest.toml`](../examples/palimpsest.toml). Overrides
   merge onto the defaults key by key: setting one threshold does not
   reset the others.
3. **Private files**, referenced by path from the project config's
   `[private]` section — gitignored, and **absent is not an error**. A
   fresh clone with no private files configured translates with an empty
   entity list and output paths that mirror the source-relative path. This
   is what makes `git clone && palimpsest translate sample.pdf` work with
   no setup.

Run `palimpsest config init` (lands in a later stage of this project) to
scaffold a `private/` directory with its own `.gitignore` — two
independent excludes are required before anything under it can be
committed by accident.

## Path resolution

Every relative path in `palimpsest.toml` resolves against the directory
**containing that file**, not the directory you run `palimpsest` from.
Paths always use forward slashes in the TOML, regardless of OS — see
`palimpsest.core.paths.norm_rel`, which normalizes a literal backslash
(from a Windows-authored file) and NFC/NFD accent differences (from a
macOS-authored one) to the same canonical form.

## The private entity file

Referenced by `[private].entities`. Lists proper nouns — company names,
personal names, place names — that must survive translation verbatim
instead of being "helpfully" translated by a machine translator. See
[`examples/entities.example.toml`](../examples/entities.example.toml) for
the schema. Accent-stripped and case-insensitive variants of every entry
are generated automatically; you don't need to list both spellings of a
name that appears both accented and unaccented in your source documents.

## The private documents file

Referenced by `[private].documents`. Maps source-relative document paths
to output-relative ones, and lists directories/files to copy through
untranslated. See
[`examples/documents.example.toml`](../examples/documents.example.toml).
This file — not the public project config — is where copy-as-is entries
live, because a copy-as-is entry is still a real filename from your real
documents.

## Glossaries

`[glossary].domains` selects one or more bundled exact-match term lists,
consulted before machine translation. Run `palimpsest glossary list`
(later stage) to see what's available; as of this writing:

| Domain | Covers |
|---|---|
| `legal` | Dominican corporate/legal/regulatory terminology |
| `ifrs` | IFRS / audited-financial-statement labels and note headings |
| `construction` | Construction-budget / bill-of-quantities terminology |

Domains are complementary, not mutually exclusive — pick the ones relevant
to what you're translating. `[glossary].extra` adds your own TOML files
(same `[terms]` table schema) on top, in order; later sources win on key
collisions, and every collision is logged.

`[glossary].heading_numbers = true` (the default) lets a glossary entry
for a bare heading match even when the document numbers it — `"2.26
Reconocimiento de ingresos"` hits the glossary entry for `"Reconocimiento
de ingresos"` and the number is re-attached to the result.

## Backends

`[backend].name` selects the primary translation backend (`"gemini"`,
`"anthropic"`, or `"google"`); `[backend].fallback` is used if the primary
errors or refuses. `"gemini"` is the default — it needs `$GEMINI_API_KEY`
(or `$GOOGLE_API_KEY`) in your environment, a free key from Google AI
Studio. The Anthropic backend needs `$ANTHROPIC_API_KEY`. Never put an API
key in `palimpsest.toml`. See [`docs/design/backends.md`](design/backends.md)
for the pricing/model tradeoffs, why Gemini is the default despite Claude
being the stronger model, and how prompt caching and the Batches API
affect cost on a large corpus run.

## Thresholds

`[thresholds]` values (bold-detection stem ratio, OCR size-jitter
tolerance, minimum readable text size, etc.) are **corpus-fitted starting
points, not universal constants** — see
[`docs/design/bold-calibration.md`](design/bold-calibration.md) for how
the bold threshold specifically was derived, and re-fit your own if your
documents behave differently.
