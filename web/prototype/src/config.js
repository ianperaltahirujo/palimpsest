// Two modes this app can run in:
//
// - REAL (default): talks to the palimpsest server. In production
//   `palimpsest serve` mounts this built app and the API at the SAME
//   origin, so the API base is "" (relative `/api/...` fetches). In
//   dev, `npm run dev`'s Vite proxy forwards `/api` to the CLI's
//   default port automatically (see vite.config.js) -- VITE_API_BASE
//   is only needed to override a non-default --port.
// - MOCK (VITE_MOCK=1): the design prototype as it existed before this
//   pass -- fixtures from state.jsx, the dev switcher, zero network
//   calls. `npm run dev` normally targets REAL mode now; MOCK is the
//   explicit opt-in for design review with no server running at all.
export const MOCK = import.meta.env.VITE_MOCK === "1";

// A THIRD deployment shape, alongside the two above: a standalone build
// (VITE_STANDALONE=1, set only by the GitHub Pages workflow) published
// at a public origin with no API of its own -- every user runs their
// own `palimpsest serve` locally and this page must be told where to
// find it. That can't be a build-time constant (one public build, many
// different users' servers), so it's a runtime setting backed by
// localStorage instead, defaulting to the CLI's own --port default.
const STORAGE_KEY = "pp-api-base";
const BUILT_IN_DEFAULT =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.VITE_STANDALONE === "1" ? "http://127.0.0.1:8765" : "");

export function getApiBase() {
  return localStorage.getItem(STORAGE_KEY) ?? BUILT_IN_DEFAULT;
}

export function setApiBase(url) {
  // An empty value means "go back to the built-in default" rather than
  // a literal empty-string base (which would silently become same-origin
  // relative fetches -- almost never what clearing the field means).
  if (url) {
    localStorage.setItem(STORAGE_KEY, url);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}
