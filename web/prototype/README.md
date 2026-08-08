# web UI

A React + Mantine frontend for palimpsest, wired to the real FastAPI
server in `src/palimpsest/server/` — upload a document, get a real
estimate, watch a real translation run, download a real replica. See the
root [`README.md`](../../README.md#web-ui) for how to install and run
`palimpsest serve`.

```
cd web/prototype
npm install
npm run dev      # http://localhost:5173, real API by default
npm run build    # -> dist/
npm test         # vitest
npm run lint     # eslint
```

This is a Vite build, not a static file — Mantine publishes no CDN/UMD
bundle, so opening `index.html` by double-click doesn't work.

## Two modes

- **Real (default).** Talks to the palimpsest server over `/api/...`.
  Run `palimpsest serve --dev` (binds the API only, no static mount) in
  one terminal and `npm run dev` in another; the two run on different
  ports (5173 for Vite, 8765 for the API by default), so the frontend
  needs `VITE_API_BASE` pointed at the server:

  ```
  VITE_API_BASE=http://localhost:8765 npm run dev
  ```

  In production, `palimpsest serve` (no `--dev`) mounts the built SPA and
  the API at the *same* origin (see `tools/build_frontend.py` at the repo
  root), so `VITE_API_BASE` is unset — every fetch is a same-origin
  relative path. `src/api.js` is the whole client; `src/config.js` reads
  `VITE_API_BASE`/`VITE_MOCK`.

- **Mock (`VITE_MOCK=1`).** The original design prototype: fixtures from
  `src/state.jsx`, zero network calls, the "prototype states" dev switcher
  in the bottom-right corner for jumping between all six screens and
  cycling light/dark/auto theme. Useful for design review with no server
  running at all.

  ```
  VITE_MOCK=1 npm run dev
  ```

  Every screen branches on `MOCK` (from `config.js`) before touching
  `api.js`, so the mock path never depends on a server existing. The app
  opens on Overview in dark mode by default in both modes; the language
  switch and theme toggle persist across reloads (`localStorage`).

The signature interaction is the wipe, on the Sample screen and inside
Results → "View on page": drag the divider, or focus it and use the arrow
keys, to compare the source and translated page in exact registration. In
real mode, both images are `/api/jobs/{id}/pages/{n}.png` — see
`server/routes.py`'s `DEFAULT_PAGE_DPI` for why that route and the edit
surface's overlay math have to agree on a raster size.

## Stack

- **Mantine** (`@mantine/core`, `@mantine/hooks`, `@mantine/dropzone`,
  `@mantine/notifications`, `@mantine/tiptap`) for every component —
  `AppShell`, `Radio.Card`, `Dropzone`, toasts, the rich text editor.
  `src/theme.js` maps the Registration system's tokens (`--register` /
  `--under` / `--flag`, Archivo Expanded / IBM Plex) onto a Mantine theme.
- `src/index.css` holds only what Mantine has no component for: the
  animated logo, the sun/moon theme icon, the wipe/page-stack geometry,
  and the edit-mode paragraph boxes.
- **TipTap**, via `@mantine/tiptap`'s `RichTextEditor`, for in-place
  paragraph editing (see Edit mode below). Loaded lazily (`React.lazy` in
  `CompareStage.jsx`, its own `manualChunks` bundle in `vite.config.js`)
  since it's only needed once someone reaches that screen.
- **Vitest** + **React Testing Library** for `src/api.test.js` (the fetch
  client's error handling and URL building) and `src/state.test.jsx` (the
  `AppStateProvider` reducer-like logic) — `vitest.setup.js` wires up
  `@testing-library/jest-dom` and the React 19 `act()` environment flag.

## Language (English/Spanish)

The flag button in the header (next to the theme toggle) switches the
whole UI between English and Spanish — every screen, both edit-mode
toolbars, aria-labels, and notification text. `src/strings.js` holds a
flat EN/ES dictionary; `src/i18n.jsx` provides `useT()` (a `t(key,
params)` lookup with `{param}` interpolation) and a `<T k="..."/>`
component for the handful of strings carrying inline `**bold**` /
`` `code` `` markup. Choice persists in `localStorage` (`pp-lang`) and
sets `<html lang>`.

Deliberately **not** translated: document/file names, legal entity
names, the Spanish source quotations under "What didn't translate" on
Results (that's document content, not UI copy), model names, and — in
real mode only — the phase `detail` strings a running job reports (they
come out of the Python pipeline in English; see `core/progress.py`).

## Vendor colour containment (backend selector)

Gemini's blue-purple gradient, Claude's orange, and Google's blue live
**only** on the backend selector's left bar and its selection indicator
(`src/components/BackendSelector.jsx`, `.pp-backend-bar` /
`.pp-backend-indicator` in `index.css`). The indicator is white by
default and takes the vendor's colour only once checked. Nowhere else in
the app uses a vendor hue — the Registration system already uses
blue/magenta *semantically* (translated layer vs. original), and a leaked
vendor colour would corrupt that language.

In real mode the API-key field is a **read-only status readout**
("`GEMINI_API_KEY` — detected" / "not set"), not an input — the server
reads keys from its own process environment exactly like the CLI and
never accepts one over HTTP (`GET /api/health`'s
`anthropic_key_present`/`gemini_key_present` booleans, never the values).
The typed key input only exists in mock mode, where it was always a fake
650ms `setTimeout`.

## Edit mode

Inside the compare view (Results → "View on page"), the Compare/Edit
segmented control switches to a live editing surface over the translated
page — select a paragraph, format text with Mantine's `RichTextEditor`
(bold, italic, underline, highlight, text colour), change alignment,
drag to move, resize width, delete/restore, undo, and export the edits
as JSON (real mode: `PATCH /api/jobs/{id}/layout`). Edit is the default
mode. Zoom controls (−, reset, +) live in the toolbar's second row, next
to the delete-paragraph button.

Every format/align/history/colour control is genuinely `disabled` (not
just dimmed) until a paragraph is actually in text-edit mode — a plain
click only *selects* a paragraph (for move/resize/delete); double-click,
Enter, or F2 enters text-edit, which is what the toolbar acts on. This
is load-bearing: the toolbar's controls all drive one shared TipTap
editor instance, and clicking them while only "selected" used to format
that shared instance's disconnected content invisibly, with no visible
effect on the paragraph on screen. Delete is the one exception — it acts
on the selection directly and works without entering text-edit.

Real mode runs on the **actual translated document**: `GET
/api/jobs/{id}/layout` runs `palimpsest.pdf.layout.extract_paragraphs` +
`page_to_ir` over the real output PDF (`server/routes.py`'s
`_layout_envelope`) — not a fixture. Mock mode keeps the static
`sample/layout.json` fixture, built the same way by
`sample/generate.py` against a synthetic page, for design review without
a server.

Two things worth knowing about what edit mode represents, not just how it
looks:

- **Emphasis is selection-scoped, snapped to word boundaries.**
  `pdf/render.py` resolves a font alias and colour *per word*
  (`_tokenise` splits on whitespace, then each word is measured and drawn
  in its own style), so bold/italic/colour/highlight genuinely can vary
  within a sentence — unlike a size change, which is paragraph-uniform.
  The one real constraint is word granularity: a mark can't end mid-word,
  so selecting part of a word rounds the mark out to the whole word. See
  `src/edit/runs.js` (`wordSnap`) for exactly how a TipTap selection maps
  back onto IR runs.
- **The per-box "fits / will shrink / will overflow" chip is a browser
  estimate**, a JS port of `layout.available_rect` + `render.fit_paragraph`
  (`src/edit/capacity.js`) measured with a hidden probe element in CSS
  `pt` units. It will disagree with the server sometimes (different wrap
  algorithm, local font substitution) — it's labelled "estimated" for
  exactly that reason, and it recomputes for the whole page (not just the
  touched box) on every move or delete, since capacity is
  neighbour-dependent.

Underline and highlight render live in the browser here, but **the real
renderer cannot draw either yet** — `pdf/render.py` draws through exactly
two `page.insert_text()` calls and nothing else. Adding those two drawing
primitives (plus `Run.underline`/`Run.highlight` on the IR) is specified
but not built. **There is also no IR→PDF reflow path in the library** —
`PATCH /api/jobs/{id}/layout` persists whatever the client sends as a
draft (see `server/routes.py`'s `patch_layout`) but does not regenerate
the PDF; the UI's own notice says so ("saved as a draft... edits don't
regenerate the PDF yet"). Edit mode is also scoped to digital PDFs only:
the overlay masks previously-drawn text with flat paper, which is honest
on a digital page and would misrepresent a scan, where the background is
a photograph.

## Contents

- `src/App.jsx` — the `AppShell` layout, six-state routing (`state.jsx`).
- `src/api.js` — the whole HTTP client (one function per server route),
  `ApiError`, and `watchJob()` (the SSE progress subscription).
- `src/config.js` — `MOCK`/`API_BASE`, read once from Vite env vars.
- `src/components/` — one file per screen/control (`Overview`, `Sample`,
  `Queue`, `Estimate`, `Running`, `Results`, `CompareStage`,
  `BackendSelector`, `Rail`, `Logo`, `ThemeToggle`, `LangToggle`,
  `ErrorBoundary`, `DevSwitcher`).
- `src/edit/` — edit mode: `EditSurface.jsx` (the TipTap-backed editing
  surface), `useEditBoxes.js` (edit state + undo stack), `capacity.js`
  (the `available_rect`/`fit_paragraph` ports), `runs.js` (TipTap ↔ IR
  run mapping).
- `src/theme.js` — Registration tokens as a Mantine theme.
- `src/strings.js`, `src/i18n.jsx` — the English/Spanish dictionary and
  the `useT()`/`<T>` lookup (see Language above).
- `public/fonts/` — three bundled OFL faces (Archivo, IBM Plex Sans, IBM
  Plex Mono), subset to Latin-1, served as static assets.
- `public/sample/` — `source.png`/`output.png`, the synthetic
  Spanish/English page pair used by the wipe demo and mock-mode edit mode.
- `src/sample/layout.json` — the real extracted-IR fixture for mock mode,
  imported directly as a JS module (Vite's module graph doesn't cover
  `public/`, which is why this one file lives under `src/` instead of
  alongside the PNGs).
- `sample/generate.py` — regenerates the three files above. Entirely
  fictional content — the de-identified cast from
  `docs/design/protected-entities.md` (Grupo Meridian, Banco Litoral,
  Andrés Carreño) — never real corpus material. Must never grow a way to
  point at a real document (no `--from` path); `tools/scrub_check.py`
  gates CI on the tracked tree.
