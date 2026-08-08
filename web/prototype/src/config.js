// Two modes this app can run in:
//
// - REAL (default): talks to the palimpsest server. In production
//   `palimpsest serve` mounts this built app and the API at the SAME
//   origin, so API_BASE is "" (relative `/api/...` fetches). In dev,
//   run `palimpsest serve --dev` (binds the API, no static mount) and
//   `npm run dev` (Vite) side by side; VITE_API_BASE points this app at
//   the server's own origin since Vite's port and the API's port
//   differ.
// - MOCK (VITE_MOCK=1): the design prototype as it existed before this
//   pass -- fixtures from state.jsx, the dev switcher, zero network
//   calls. `npm run dev` normally targets REAL mode now; MOCK is the
//   explicit opt-in for design review with no server running at all.
export const MOCK = import.meta.env.VITE_MOCK === "1";

export const API_BASE = import.meta.env.VITE_API_BASE || "";
