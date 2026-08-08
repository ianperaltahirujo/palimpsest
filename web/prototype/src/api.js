import { getApiBase } from "./config.js";

// Thin fetch wrapper for the palimpsest server (src/palimpsest/server/).
// Every function here mirrors one route in server/routes.py 1:1 -- see
// that file for the shapes returned. Errors always throw an ApiError so
// callers get one catch shape regardless of which call failed.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, options);
  } catch (e) {
    // Network-level failure (server not running, refused connection) --
    // distinct from an HTTP error status, which the caller may want to
    // handle differently (e.g. 404 "not ready yet" vs. "no server at all").
    throw new ApiError(`could not reach the server -- is \`palimpsest serve\` running? (${e.message})`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new ApiError(detail, res.status);
  }
  return res;
}

async function requestJson(path, options) {
  const res = await request(path, options);
  // A 200 with an HTML body happens when there's no /api proxy/route at all
  // (e.g. `npm run dev` without a live palimpsest server behind it) and the
  // request falls through to a dev server's or static host's SPA fallback.
  // request() only checks res.ok, so that case reaches here looking like
  // success -- reject it explicitly instead of letting res.json() throw an
  // opaque parse error that callers can't distinguish from "key missing".
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      `unreachable server -- is \`palimpsest serve\` running? (got a non-JSON response from ${path})`,
      0,
    );
  }
  return res.json();
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function health() {
  return requestJson("/api/health");
}

// keys: {anthropic_api_key?, gemini_api_key?} -- an absent/empty field is
// a no-op server-side, not a clear (server/schemas.py's SetKeysRequest).
// Returns the same shape health() does; never echoes the raw value back.
export function setKeys(keys) {
  return requestJson("/api/keys", {
    method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(keys),
  });
}

export function getEntities() {
  return requestJson("/api/entities");
}

export function putEntities(groups) {
  return requestJson("/api/entities", {
    method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(groups),
  });
}

export async function uploadFile(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  // Plain fetch has no upload-progress event; onProgress is accepted for
  // API-shape symmetry with a future XHR-based version but is a no-op
  // for now -- callers must not rely on it firing.
  void onProgress;
  return requestJson("/api/uploads", { method: "POST", body: form });
}

export function estimate(fileIds) {
  return requestJson("/api/estimate", {
    method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ file_ids: fileIds }),
  });
}

export function createJob(fileIds, { backend, dual = true } = {}) {
  return requestJson("/api/jobs", {
    method: "POST", headers: JSON_HEADERS,
    body: JSON.stringify({ file_ids: fileIds, backend: backend || null, dual }),
  });
}

export function getJob(jobId) {
  return requestJson(`/api/jobs/${jobId}`);
}

// SSE progress. Returns an unsubscribe function. `onEvent` receives the
// parsed payload for every "progress" message; `onDone` receives
// {status, error} once for the terminal "job-done" message, after which
// the EventSource is closed automatically -- callers never need to
// close it themselves on the happy path, only via the returned
// unsubscribe if they navigate away early.
export function watchJob(jobId, { onEvent, onDone, onError } = {}) {
  const source = new EventSource(`${getApiBase()}/api/jobs/${jobId}/events`);
  source.onmessage = (msg) => {
    let payload;
    try {
      payload = JSON.parse(msg.data);
    } catch {
      return;
    }
    if (payload.type === "job-done") {
      onDone?.(payload);
      source.close();
    } else {
      onEvent?.(payload);
    }
  };
  source.onerror = (e) => {
    onError?.(e);
  };
  return () => source.close();
}

export function downloadUrl(jobId, artifact, fileId) {
  const q = fileId ? `?file=${encodeURIComponent(fileId)}` : "";
  return `${getApiBase()}/api/jobs/${jobId}/download/${artifact}${q}`;
}

export function pageUrl(jobId, pageNo, { side = "output", fileId, dpi, v } = {}) {
  const params = new URLSearchParams({ side });
  if (fileId) params.set("file", fileId);
  if (dpi) params.set("dpi", String(dpi));
  // Cache-buster: the browser has no way to know a reflowed page's PNG
  // changed underneath the same URL, since the server route ignores
  // unknown params -- bump `v` (e.g. a save counter) after a successful
  // PATCH /layout so the <img> actually re-fetches.
  if (v !== undefined) params.set("v", String(v));
  return `${getApiBase()}/api/jobs/${jobId}/pages/${pageNo}.png?${params}`;
}

export function getLayout(jobId, { fileId, page = 0 } = {}) {
  const params = new URLSearchParams({ page: String(page) });
  if (fileId) params.set("file", fileId);
  return requestJson(`/api/jobs/${jobId}/layout?${params}`);
}

export function patchLayout(jobId, body, { fileId } = {}) {
  const q = fileId ? `?file=${encodeURIComponent(fileId)}` : "";
  return requestJson(`/api/jobs/${jobId}/layout${q}`, {
    method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body),
  });
}
