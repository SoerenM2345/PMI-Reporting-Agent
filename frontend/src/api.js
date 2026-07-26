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
  // A multipart body must NOT carry a Content-Type header — the browser sets
  // it, boundary and all. Sending the JSON header with a FormData body makes
  // the upload arrive unparseable.
  const isForm = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(options.headers ?? {}),
    },
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

/** Upload into a chat — a real conversational turn: the files are stored in the
 *  transcript, everything is re-read, and the reply says what changed. This
 *  replaced the bare `/api/upload` side effect the pre-chat wizard used. */
export async function addChatFiles(chatId, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  // No Content-Type header — the browser must set the multipart boundary.
  return call(`/api/chats/${chatId}/files`, { method: "POST", body: form });
}

export function resolveConflicts(sessionId, choices) {
  return call(`/api/conflicts/${sessionId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ choices }),
  });
}

export function downloadUrl(sessionId, filename) {
  return `/api/download/${sessionId}/${encodeURIComponent(filename)}`;
}

/** Defensive read: "Not Reported" and null are legitimate values everywhere (§7). */
export function show(value, fallback = "Not Reported") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

/* ------------------------------------------------------------------ chats */
/* A chat owns a session. Everything above still works on the session id, so
   the wizard-era endpoints are unchanged — the chat layer sits on top. */

export function createChat(payload = {}) {
  return call("/api/chats", { method: "POST", body: JSON.stringify(payload) });
}

export function listChats(includeArchived = false) {
  return call(`/api/chats?include_archived=${includeArchived}`);
}

export function getChat(chatId) {
  return call(`/api/chats/${chatId}`);
}

export function patchChat(chatId, patch) {
  return call(`/api/chats/${chatId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteChat(chatId) {
  return call(`/api/chats/${chatId}`, { method: "DELETE" });
}

export function sendMessage(chatId, text) {
  return call(`/api/chats/${chatId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

/* --------------------------------------------------------------- projects */
/* A project is a folder over chats plus a knowledge scratchpad. It owns no
   session; a chat carries `project_id` to say which folder it lives in, and
   null means "outside any project". */

export function listProjects() {
  return call("/api/projects");
}

export function createProject(payload = {}) {
  return call("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getProject(projectId) {
  return call(`/api/projects/${projectId}`);
}

export function patchProject(projectId, patch) {
  return call(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteProject(projectId) {
  return call(`/api/projects/${projectId}`, { method: "DELETE" });
}

/* --------------------------------------------------------- report content */
/* The preview loop: plan -> read -> revise -> render. None of these re-run
   extraction, so iterating on wording is free. */

export function planContent(sessionId) {
  return call(`/api/content/${sessionId}`, { method: "POST" });
}

export function getContent(sessionId, version) {
  const suffix = version ? `?version=${version}` : "";
  return call(`/api/content/${sessionId}${suffix}`);
}

export function listContentVersions(sessionId) {
  return call(`/api/content/${sessionId}/versions`);
}

export function revertContent(sessionId, version) {
  return call(`/api/content/${sessionId}/revert?version=${version}`, {
    method: "POST",
  });
}

/** Edit one preview cell.
 *
 * The value is written **through to the data model** and the report re-planned,
 * so the deck, the workbook and the document all pick it up. A rejected value
 * comes back as `{applied: false, message}` — a 200 with a reason, not a 4xx the
 * UI has to translate. */
export function editCell(sessionId, { blockId, row, column, value }) {
  return call(`/api/content/${sessionId}/cell`, {
    method: "POST",
    body: JSON.stringify({ block_id: blockId, row, column, value }),
  });
}

/** Save rewritten card text (a prose or bullets block).
 *
 * The text is stored as a user override and the report re-planned, so it
 * survives the next re-plan and appears in every format. A figure the report
 * does not already hold comes back as `{applied: false, message}` — the split
 * that keeps prose editable while numbers stay owned by the data model. */
export function editProse(sessionId, { blockId, text }) {
  return call(`/api/content/${sessionId}/prose`, {
    method: "POST",
    body: JSON.stringify({ block_id: blockId, text }),
  });
}

export function reviseContent(sessionId, instruction) {
  return call(`/api/content/${sessionId}/revise`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

/** Render the approved content. `format` is optional; omitted keeps the
    original request's type. */
export function generateAs(sessionId, format, force = false) {
  return call("/api/generate", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, format, force }),
  });
}

/** The picker's options. Model IDs live only in `app/config.py` (§21.10), so
    the list is fetched rather than duplicated here. */
export function listModels() {
  return call("/api/models");
}

/** Completeness gaps (§8.2) the user can close, and closing one. */
export function listIssues(sessionId) {
  return call(`/api/issues/${sessionId}`);
}

export function fillIssue(sessionId, issueId, value) {
  return call(`/api/issues/${sessionId}/fill`, {
    method: "POST",
    body: JSON.stringify({ issue_id: issueId, value }),
  });
}
