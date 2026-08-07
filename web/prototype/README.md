# web UI — design prototype

A self-contained, static mockup of a browser UI for palimpsest, on mock
data. No backend, no network requests, nothing here calls into the
`palimpsest` package. Open `index.html` directly in a browser.

Walk all six product states — overview, sample, queue, estimate, running,
results — with the "prototype states" control in the bottom-right corner
(collapsed by default; click to expand). It also cycles light/dark/auto
theme. Neither control is part of the eventual product UI.

The signature interaction is the wipe, on the Sample screen and inside
Results → "View on page": drag the divider, or focus it and use the arrow
keys, to compare the source and translated sample page in exact
registration.

## Edit mode

Inside the compare view (Results → "View on page"), the Compare/Edit
toggle switches to a live editing surface over the translated page —
select a paragraph, edit its text, bold/italic/underline/highlight,
change alignment or colour, drag to move, resize width, delete/restore,
undo, and export the edits as JSON. This runs on **real** paragraph
geometry: `sample/generate.py` builds the sample page and then runs the
actual `palimpsest.pdf.layout.extract_paragraphs` + `page_to_ir` over it,
so `sample/layout.json`/`layout.js` are genuine library output, not a
hand-built approximation — see that script's docstring.

Two things worth knowing about what edit mode represents, not just how it
looks:

- **Emphasis is whole-phrase, not per-character.** The real renderer
  stores styling per run and cannot represent mid-sentence emphasis
  (`docs/design/limitations.md`), so selecting three words and pressing
  bold formats the *whole run* the caret is in — the affected run flashes
  so that's visible rather than implied by a floating selection popup.
- **The per-box "fits / will shrink / will overflow" chip is a browser
  estimate**, a JS port of `layout.available_rect` + `render.fit_paragraph`
  measured with a hidden probe element in CSS `pt` units. It will disagree
  with the server sometimes (different wrap algorithm, local font
  substitution) — it's labelled "estimated" for exactly that reason, and
  it recomputes for the whole page (not just the touched box) on every
  move or delete, since capacity is neighbour-dependent.

Underline and highlight render live in the browser here, but **the real
renderer cannot draw either yet** — `pdf/render.py` draws through exactly
two `page.insert_text()` calls and nothing else. Adding those two drawing
primitives (plus `Run.underline`/`Run.highlight` on the IR) is specified
but not built; see the plan this prototype came from. Edit mode is also
scoped to digital PDFs only: the overlay masks previously-drawn text with
flat paper, which is honest on a digital page and would misrepresent a
scan, where the background is a photograph.

## What this is not

This is the design-prototype pass only, scoped per the plan that produced
it (`docs/design/` doesn't cover this yet — see the repo's web UI
planning notes). It does not wire up to a real FastAPI backend, does not
call `translate_pdf_document()` or any other library entry point, and the
API contract it mocks (`POST /api/jobs`, SSE progress events, the edit
payload PATCHed to `/api/jobs/{id}/layout`, etc.) is a design surface, not
an implemented one. The IR→PDF render path that would turn an edit-mode
export back into a real PDF does not exist in the library yet either.

## Contents

- `index.html` — markup, CSS, and JS in one file; mock fixtures inline.
- `fonts/` — three bundled OFL faces (Archivo, IBM Plex Sans, IBM Plex
  Mono), subset to Latin-1, so the page renders identically offline.
- `sample/` — the synthetic Spanish/English page pair used by the wipe
  demo and edit mode, plus the script that generated them
  (`generate.py`) and the real extracted-IR fixture it also emits
  (`layout.json`/`layout.js`). Entirely fictional content — the
  de-identified cast from `docs/design/protected-entities.md` (Grupo
  Meridian, Banco Litoral, Andrés Carreño) — never real corpus material.
  `generate.py` must never grow a way to point at a real document (no
  `--from` path); `tools/scrub_check.py` gates CI on the tracked tree.
