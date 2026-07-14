/**
 * The ONLY module that talks to the backend.
 *
 * The API is untyped at this boundary (plain JS, per spec §15), so the guard against
 * shape drift is convention rather than a compiler: every response shape is read here
 * and nowhere else. If the backend renames a field, exactly one file changes.
 *
 * The Pydantic response models in `app/main.py` are the source of truth. When in
 * doubt, read them, or open http://localhost:8000/docs.
 */

async function call(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {
    // A 500 with an HTML body, or an empty 204.
  }

  if (!response.ok) {
    const error = new Error(
      body?.detail?.message || body?.detail || `${response.status} ${response.statusText}`,
    );
    error.status = response.status;
    error.detail = body?.detail;
    throw error;
  }

  return body;
}

export function createSession() {
  return call("/api/session", { method: "POST" });
}

export function setProject(payload) {
  return call("/api/project", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function uploadFiles(sessionId, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  // No Content-Type header: the browser must set the multipart boundary itself.
  const response = await fetch(`/api/upload?session_id=${sessionId}`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
  return response.json();
}

export function analyze(payload) {
  return call("/api/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resolveConflicts(sessionId, choices) {
  return call(`/api/conflicts/${sessionId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ choices }),
  });
}

export function generate(sessionId, force = false) {
  return call("/api/generate", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, force }),
  });
}

export function getQuality(sessionId) {
  return call(`/api/quality/${sessionId}`);
}

export function downloadUrl(sessionId, filename) {
  return `/api/download/${sessionId}/${encodeURIComponent(filename)}`;
}

/** Defensive read: "Not Reported" and null are legitimate values everywhere (§7). */
export function show(value, fallback = "Not Reported") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}
