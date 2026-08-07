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

/**
 * The in-flight turn, so it can be stopped.
 *
 * One at a time by construction: the UI disables send while a turn is running,
 * and a second call would abandon a request whose reply is already being
 * waited on.
 */
let inFlight = null;

/** Stop the running turn. The server sees the disconnect and stops too. */
export function abort() {
  inFlight?.abort();
  inFlight = null;
}

export class Aborted extends Error {}

async function call(path, options = {}) {
  // A multipart body must NOT carry a Content-Type header — the browser sets
  // it, boundary and all. Sending the JSON header with a FormData body makes
  // the upload arrive unparseable.
  const isForm = options.body instanceof FormData;

  let controller = null;
  if (options.abortable) {
    controller = new AbortController();
    inFlight = controller;
  }

  let response;
  try {
    response = await fetch(path, {
      ...options,
      signal: controller?.signal,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(options.headers ?? {}),
      },
    });
  } catch (error) {
    // A cancelled turn is an outcome the user asked for, not a failure — the
    // caller distinguishes it so the UI shows "stopped" rather than an error
    // banner.
    if (error.name === "AbortError") throw new Aborted("stopped");
    throw error;
  } finally {
    if (controller && inFlight === controller) inFlight = null;
  }

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

/**
 * One turn: a message, some files, or both, in a single request.
 *
 * Two sequential POSTs is what this replaced, and the ordering was the bug —
 * `/files` re-runs the whole analysis synchronously, so when it threw the
 * message call never fired and the user's typed sentence was silently dropped.
 * One request is also the only thing Stop can meaningfully cancel.
 */
export function sendTurn(chatId, text, files = []) {
  const form = new FormData();
  form.append("text", text ?? "");
  for (const file of files) form.append("files", file);
  return call(`/api/chats/${chatId}/turn`, {
    method: "POST",
    body: form,
    abortable: true,
  });
}

/* --------------------------------------------------------------- projects */
/* A project is a folder over chats plus a knowledge scratchpad. It owns no
   session; a chat carries `project_id` to say which folder it lives in, and
   null means "outside any project". */

export function listProjects() {
  return call("/api/projects");
}

/** Search project names/knowledge plus titles and text across every live chat. */
export function searchApp(query) {
  return call(`/api/search?q=${encodeURIComponent(query)}`);
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

export function approveContent(sessionId, version, format) {
  return call(`/api/content/${sessionId}/approve`, {
    method: "POST",
    body: JSON.stringify({ version, format }),
  });
}

/** Render the approved content. `format` is optional; omitted keeps the
    original request's type. */
export function generateAs(sessionId, format, force = false, approvalId = null, version = null) {
  return call("/api/generate", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      format,
      force,
      approval_id: approvalId,
      version,
    }),
  });
}

/** The picker's options. Model IDs live only in `app/config.py` (§21.10), so
    the list is fetched rather than duplicated here. */
export function listModels() {
  return call("/api/models");
}

/* ------------------------------------------------ project workspace (§Phase 3-5) */
/* The project-centric, continuously-updating flow: every uploaded file becomes a
   source, knowledge re-derives incrementally, drafts are editable and versioned,
   and export happens only when asked. Keyed by `project_id`, not a session. */

/** The one conversational endpoint: a message (with optional context) → a Markdown
    reply plus structured actions/warnings/conflict_state. */
export function chat(payload) {
  return call("/api/chat", { method: "POST", body: JSON.stringify(payload) });
}

/** Continuous ingestion: upload files into a project. Returns the new knowledge
    version and any drafts the change flagged stale. */
export function uploadProjectFiles(projectId, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return call(`/api/projects/${projectId}/files`, { method: "POST", body: form });
}

export function getProjectKnowledge(projectId) {
  return call(`/api/projects/${projectId}/knowledge`);
}

export function listDrafts(projectId) {
  return call(`/api/projects/${projectId}/drafts`);
}

export function createDraft(projectId, payload = {}) {
  return call(`/api/projects/${projectId}/drafts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDraft(projectId, draftId) {
  return call(`/api/projects/${projectId}/drafts/${draftId}`);
}

/** A direct user edit → a new draft version. Pass either `{ section_id, text }`
    for one section, or `{ title, content }` for the whole draft. */
export function patchDraft(projectId, draftId, patch) {
  return call(`/api/projects/${projectId}/drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function regenerateSection(projectId, draftId, sectionId) {
  return call(`/api/projects/${projectId}/drafts/${draftId}/regenerate-section`, {
    method: "POST",
    body: JSON.stringify({ section_id: sectionId }),
  });
}

export function listDraftVersions(projectId, draftId) {
  return call(`/api/projects/${projectId}/drafts/${draftId}/versions`);
}

export function restoreDraftVersion(projectId, draftId, version) {
  return call(`/api/projects/${projectId}/drafts/${draftId}/restore-version`, {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

/** Export the latest saved draft. Returns `{ file, download_url }` — the file is
    built from the draft, so it matches the approved text (Scenario 6). */
export function exportDraft(projectId, draftId, format) {
  return call(`/api/projects/${projectId}/drafts/${draftId}/export`, {
    method: "POST",
    body: JSON.stringify({ format }),
  });
}

export function exportDownloadUrl(projectId, filename) {
  return `/api/projects/${projectId}/exports/${encodeURIComponent(filename)}`;
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

// ============================================================ LLM-driven flow

/** Generate content from uploaded files using LLM. */
export function generateContent(sessionId, request, { outputFormat = "PowerPoint", audience = null } = {}) {
  return call("/api/llm/generate", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, request, output_format: outputFormat, audience }),
    abortable: true,
  });
}

/** Revise generated content based on user feedback. */
export function reviseContent(sessionId, revision) {
  return call("/api/llm/revise", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, revision }),
    abortable: true,
  });
}

/** Get current generated content. */
export function getContent(sessionId) {
  return call(`/api/llm/content/${sessionId}`);
}

/** Get HTML preview of current content. */
export function getPreview(sessionId) {
  return call(`/api/llm/preview/${sessionId}`);
}

/** Approve current content for rendering. */
export function approveContent(sessionId) {
  return call("/api/llm/approve", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

/** Generate output files in specified formats. */
export function generateFiles(sessionId, version, formats) {
  return call("/api/llm/generate-files", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, version, formats }),
    abortable: true,
  });
}

/** List all approved content versions. */
export function listVersions(sessionId) {
  return call(`/api/llm/versions/${sessionId}`);
}

/** Get specific version content. */
export function getVersion(sessionId, version) {
  return call(`/api/llm/versions/${sessionId}/${version}`);
}

/** Get HTML preview of specific version. */
export function getVersionPreview(sessionId, version) {
  return call(`/api/llm/versions/${sessionId}/${version}/preview`);
}

/** Download URL for generated file. */
export function downloadUrl(sessionId, filename) {
  return `/api/llm/download/${sessionId}/${encodeURIComponent(filename)}`;
}
