// Per-backend API-key cache in the browser, so the key box works even
// before a local server is reachable (the standalone/GitHub Pages build's
// whole reason for existing -- see config.js's VITE_STANDALONE). A cached
// key is held here until a server answers, then auto-pushed via
// PUT /api/keys (see state.jsx's health-driven push) -- the server, not
// this cache, is always the real source of truth once reachable.
//
// SECURITY: this is localStorage, scoped to the page's ORIGIN, not its
// path. A standalone build published at https://<user>.github.io/<repo>/
// shares that origin with every OTHER project the same user publishes
// under github.io -- any of them can read a key cached here. Self-hosting
// this build under your own domain does not have that exposure. See
// SECURITY.md.
export const CACHEABLE_BACKENDS = ["anthropic", "gemini"];

const storageKey = (backend) => `pp-key-${backend}`;

export function getCachedKey(backend) {
  return localStorage.getItem(storageKey(backend));
}

export function setCachedKey(backend, value) {
  if (value) {
    localStorage.setItem(storageKey(backend), value);
  } else {
    localStorage.removeItem(storageKey(backend));
  }
}

export function clearCachedKey(backend) {
  localStorage.removeItem(storageKey(backend));
}

// Shared backend <-> {env var, health-field, PUT /api/keys field} maps --
// single source of truth for state.jsx's auto-push logic and
// BackendSelector.jsx's rendering, which both need the same three
// mappings kept in sync.
export const ENV_VAR = { anthropic: "ANTHROPIC_API_KEY", gemini: "GEMINI_API_KEY" };
export const HEALTH_KEY = { anthropic: "anthropic_key_present", gemini: "gemini_key_present" };
export const KEY_FIELD = { anthropic: "anthropic_api_key", gemini: "gemini_api_key" };
