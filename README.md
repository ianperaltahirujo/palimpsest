# palimpsest

*A palimpsest is a manuscript page scraped clean so the surface can be
reused — the original artwork and impressions intact, new text written
over it. That's what this tool does to a document: same pages, same
artwork, same typography — only the words change.*

**Status: early scaffold.** The package skeleton, config schema, and CI are
in place; the translation pipeline itself is being ported over in stages
(see `docs/design/` as it fills in). Not yet installable as a working
translator — track progress via the repository's PR history.

## What this will do

Layout-preserving document translation for PDF and Office formats
(.pptx/.xlsx/.docx): OCR when there's no text layer, styled-run extraction,
in-place redraw with real embedded fonts, entity/glossary-aware machine
translation (Google or Claude backends), and an honest translation cache
that never lets a failed translation masquerade as a successful one.

Full design rationale — including a detailed postmortem of the layout,
font, and translation-correctness bugs this project exists to avoid
repeating — will land in `docs/design/` as each subsystem is ported.

## License

Apache 2.0 — see `LICENSE`. See `NOTICE` for a design-inspiration credit to
[BabelDOC](https://github.com/funstory-ai/BabelDOC) (AGPL-3.0; no code
shared).
