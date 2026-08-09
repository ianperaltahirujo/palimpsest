// Browser-generated visitor identity -- no accounts, no login. A random id
// is minted once per browser (crypto.randomUUID()) and cached in
// localStorage, same pattern as config.js's api-base override and
// keys.js's key cache. This is the only thing that lets a shared,
// publicly-hosted server (see docs/deployment) keep one visitor's uploads,
// jobs, and keys from being visible to another -- it is NOT an auth
// mechanism (nothing is signed, nothing stops a client from sending a
// different id on purpose) and isn't meant to be one; see the server-side
// plan notes for what it does and doesn't defend against.
const STORAGE_KEY = "pp-visitor-id";

export function getVisitorId() {
  let id = localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}
