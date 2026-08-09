// Saved protected-entity rosters, browser-local. GET/PUT /api/entities
// (server/routes.py) read and write ONE SHARED GLOBAL file -- there is
// no `visitor_id` anywhere in that code path, unlike uploads/jobs/keys.
// On a hosted deployment every visitor already sees and overwrites the
// same roster (a pre-existing fact, not introduced here); server-side
// profile storage would make that actively worse -- one visitor's saved
// profile leaking into, and being overwritable by, every other visitor.
// So profiles live here instead, same pattern as keys.js/visitor.js:
// a `pp-`-prefixed localStorage key, one small dedicated module.
const STORAGE_KEY = "pp-entity-profiles";

function readAll() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(profiles) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(profiles));
}

export function getProfiles() {
  return readAll();
}

// "Save As" semantics: a name matching an existing profile overwrites
// it in place (same id, refreshed `savedAt`) rather than creating a
// duplicate -- this is also how "editing" a profile works (load it,
// tweak the chips with the existing add/remove/move UI, save again
// under the same name), with no separate editing surface needed.
export function saveProfile(name, groups) {
  const trimmed = name.trim();
  if (!trimmed) return getProfiles();
  const profiles = readAll();
  const existing = profiles.find((p) => p.name === trimmed);
  const entry = {
    id: existing?.id ?? crypto.randomUUID(),
    name: trimmed,
    groups: structuredClone(groups),
    savedAt: Date.now(),
  };
  const next = existing
    ? profiles.map((p) => (p.id === existing.id ? entry : p))
    : [...profiles, entry];
  writeAll(next);
  return next;
}

export function deleteProfile(id) {
  const next = readAll().filter((p) => p.id !== id);
  writeAll(next);
  return next;
}
