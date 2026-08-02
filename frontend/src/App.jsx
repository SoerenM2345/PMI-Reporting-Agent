import { useEffect, useRef, useState } from "react";

import * as api from "./api";
import ChatProjectPicker from "./components/chat/ChatProjectPicker";
import Composer from "./components/chat/Composer";
import MessageBubble from "./components/chat/MessageBubble";
import ModelPicker from "./components/chat/ModelPicker";
import ProjectPanel from "./components/chat/ProjectPanel";
import Sidebar from "./components/chat/Sidebar";
import Thinking from "./components/chat/Thinking";
import ProjectWorkspace from "./components/report/ProjectWorkspace";

/**
 * The §4 journey, as a conversation: upload → ask → resolve → *read the draft*
 * → revise → generate.
 *
 * The wizard this replaced rendered five fixed sections and ended at download.
 * The important structural change is not the layout — it is that the transcript
 * is append-only. Uploading new files used to wipe the analysis; here it adds a
 * turn saying the earlier draft no longer matches, because a conversation you
 * can silently rewrite is not a record of anything.
 *
 * Every figure still comes from the backend. Nothing in this file computes a
 * number, and the preview a user approves is the same content the renderer uses.
 */
export default function App() {
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState(null);
  const [chat, setChat] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);

  // Projects are a filing layer over chats. `activeProject` non-null means the
  // main pane shows that project's knowledge editor instead of a conversation;
  // opening or creating a chat clears it, so the two views never overlap.
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);

  // The project-centric workspace (Phase 3-5): a /api/chat conversation plus an
  // editable, versioned report draft, both keyed by project_id. Lives here rather
  // than in the component, per the app's "all state in App.jsx" convention.
  const [projectTab, setProjectTab] = useState("workspace");
  const [wsMessages, setWsMessages] = useState([]);
  const [wsDraft, setWsDraft] = useState(null);
  const [wsVersions, setWsVersions] = useState([]);
  const [wsKnowledge, setWsKnowledge] = useState({ version: null, exists: false });
  const [wsStale, setWsStale] = useState(0);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottom = useRef(null);
  const messageCount = useRef(0);

  useEffect(() => {
    refreshProjects();
    refreshChats().then((existing) => {
      if (existing.length) openChat(existing[0].chat_id);
      else newChat();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Only follow the conversation to the bottom when a *new* turn is added.
  // Resolving a conflict (and editing a preview cell) updates a message in
  // place; scrolling then would yank the user away from the card they just
  // acted on. Guarding on the count keeps them where they were.
  useEffect(() => {
    if (messages.length > messageCount.current) {
      bottom.current?.scrollIntoView({ behavior: "smooth" });
    }
    messageCount.current = messages.length;
  }, [messages]);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      // A stopped turn is not an error. Showing the red banner for something
      // the user deliberately did reads as a failure they have to act on.
      if (!(e instanceof api.Aborted)) setError(e.message);
      return null;
    } finally {
      setBusy(false);
    }
  };

  /** Stop the running turn. The fetch aborts, the server sees the disconnect
   *  and stops between stages, and no partial file is offered as finished. */
  const stop = () => api.abort();

  const refreshChats = async () => {
    const body = await api.listChats();
    setChats(body.chats);
    return body.chats;
  };

  const refreshProjects = async () => {
    const body = await api.listProjects();
    setProjects(body.projects);
    return body.projects;
  };

  // A chat is always created inside or outside a project — `projectId` null is
  // "outside". Opening a chat leaves the project view, so the new conversation
  // is what the user is looking at.
  const newChat = (projectId = null) =>
    run(async () => {
      const body = await api.createChat({ title: "New chat", project_id: projectId });
      setActiveProject(null);
      setChatId(body.chat.chat_id);
      setChat(body.chat);
      setSessionId(body.session_id);
      setMessages([
        agentSays(
          "Upload this week's PMI files and tell me what you need. I'll read " +
            "them, show you where they disagree, and draft the report as text " +
            "before generating anything.",
        ),
      ]);
      await refreshChats();
    });

  const openChat = (id) =>
    run(async () => {
      const body = await api.getChat(id);
      setActiveProject(null);
      setChatId(id);
      setChat(body.chat);
      setSessionId(body.chat.session_id);
      setMessages(body.messages);
    });

  /* ------------------------------------------------------------ projects */

  const openProject = (id) =>
    run(async () => {
      // Fetch the full record — the list carries name/icon/counts, but the
      // knowledge text is only returned by the single-project read.
      const body = await api.getProject(id);
      setActiveProject(body.project);
      setProjectTab("workspace");
      setWsMessages([]);
      setWsVersions([]);
      setWsStale(0);
      await loadWorkspace(id);
    });

  /* --------------------------------------------------- project workspace */
  // The continuously-updating flow: files → knowledge → editable draft → export,
  // all through the project-centric endpoints. Every call goes through `run(fn)`,
  // and the refreshed draft/knowledge comes back into state so the UI can't drift
  // from the server.
  const loadWorkspace = async (projectId) => {
    const kb = await api.getProjectKnowledge(projectId);
    setWsKnowledge({ version: kb.exists ? kb.version : null, exists: kb.exists });
    const drafts = await api.listDrafts(projectId);
    setWsDraft(drafts.drafts?.[0] || null);
  };

  const wsUpload = (files) =>
    run(async () => {
      const pid = activeProject.project_id;
      const body = await api.uploadProjectFiles(pid, files);
      setWsKnowledge({ version: body.knowledge_version, exists: true });
      setWsStale((body.stale_drafts || []).length);
      if (wsDraft) {
        const d = await api.getDraft(pid, wsDraft.draft_id);
        setWsDraft(d.draft);
      }
      setWsMessages((prior) => [
        ...prior,
        wsTurn(`Processed ${body.ingested.length} file(s) — project knowledge ` +
          `updated to version ${body.knowledge_version}.`),
      ]);
    });

  const wsSend = (text) =>
    run(async () => {
      const pid = activeProject.project_id;
      setWsMessages((prior) => [
        ...prior,
        { id: `u-${Date.now()}`, role: "user", text },
      ]);
      const resp = await api.chat({
        project_id: pid,
        message: text,
        active_draft_id: wsDraft?.draft_id || null,
      });
      setWsMessages((prior) => [...prior, wsAgentTurn(pid, resp)]);
      if (resp.knowledge_version != null) {
        setWsKnowledge({ version: resp.knowledge_version, exists: true });
      }
      const staleActions = (resp.actions || []).filter((a) => a.type === "draft_stale");
      if (staleActions.length) setWsStale(staleActions.length);
      // A turn that created, updated or pointed at a draft → load it on the right.
      const target =
        resp.draft?.draft_id ||
        (resp.actions || []).find((a) => a.draft_id)?.draft_id;
      if (target) {
        const d = await api.getDraft(pid, target);
        setWsDraft(d.draft);
      }
    });

  const wsCreateDraft = () =>
    run(async () => {
      const body = await api.createDraft(activeProject.project_id, {});
      setWsDraft(body.draft);
    });

  const wsSaveSection = (sectionId, text) =>
    run(async () => {
      const body = await api.patchDraft(activeProject.project_id, wsDraft.draft_id, {
        section_id: sectionId,
        text,
      });
      setWsDraft(body.draft);
    });

  const wsRegenerate = (sectionId) =>
    run(async () => {
      const body = await api.regenerateSection(
        activeProject.project_id, wsDraft.draft_id, sectionId);
      setWsDraft(body.draft);
    });

  const wsExport = (format) =>
    run(async () => {
      const pid = activeProject.project_id;
      const body = await api.exportDraft(pid, wsDraft.draft_id, format);
      setWsMessages((prior) => [
        ...prior,
        {
          id: `x-${Date.now()}`,
          role: "agent",
          text: `Exported the saved draft as **${format}**.`,
          actions: [{ type: "download", file: body.file, url: body.download_url }],
        },
      ]);
    });

  const wsLoadVersions = () =>
    run(async () => {
      const body = await api.listDraftVersions(
        activeProject.project_id, wsDraft.draft_id);
      setWsVersions(body.versions);
    });

  const wsRestore = (version) =>
    run(async () => {
      const pid = activeProject.project_id;
      const body = await api.restoreDraftVersion(pid, wsDraft.draft_id, version);
      setWsDraft(body.draft);
      const v = await api.listDraftVersions(pid, wsDraft.draft_id);
      setWsVersions(v.versions);
    });

  const createProject = ({ name, icon }) =>
    run(async () => {
      const body = await api.createProject({ name, icon });
      await refreshProjects();
      // Drop the user straight into the new project so they can add knowledge.
      setActiveProject(body.project);
    });

  const renameProject = (id, name) =>
    run(async () => {
      const body = await api.patchProject(id, { name });
      await refreshProjects();
      if (activeProject?.project_id === id) setActiveProject(body.project);
    });

  const changeProjectIcon = (id, icon) =>
    run(async () => {
      const body = await api.patchProject(id, { icon });
      await refreshProjects();
      if (activeProject?.project_id === id) setActiveProject(body.project);
    });

  const saveProjectKnowledge = (id, knowledge) =>
    run(async () => {
      const body = await api.patchProject(id, { knowledge });
      await refreshProjects();
      setActiveProject(body.project);
      return body.project;
    });

  const addProjectRule = (id, rule) =>
    run(async () => {
      const body = await api.addProjectRule(id, rule);
      await refreshProjects();
      setActiveProject(body.project);
      return body.project;
    });

  const moveChatToProject = (existingChatId, projectId) =>
    run(async () => {
      const moved = await api.patchChat(existingChatId, { project_id: projectId });
      if (existingChatId === chatId) setChat(moved.chat);
      await refreshChats();
      await refreshProjects();
      // If the user is looking at a project, keep its counts, knowledge and
      // workspace current whether a chat was moved into or out of it.
      if (activeProject) {
        const body = await api.getProject(activeProject.project_id);
        setActiveProject(body.project);
        await loadWorkspace(activeProject.project_id);
      }
    });

  const addExistingChat = (projectId, existingChatId) =>
    moveChatToProject(existingChatId, projectId);

  const deleteProject = (id, name) =>
    run(async () => {
      // Deleting a project keeps its chats — they fall back to the top level.
      // Worth confirming anyway: it is a container the user built on purpose.
      if (!window.confirm(`Delete project “${name}”? Its chats are kept.`)) {
        return;
      }
      await api.deleteProject(id);
      await refreshProjects();
      await refreshChats();
      if (activeProject?.project_id === id) {
        setActiveProject(null);
        if (chatId) openChat(chatId);
        else newChat();
      }
    });

  // One turn = optional attachments + optional prompt, in **one** request.
  //
  // It used to be two, files first. `/files` re-runs the whole analysis
  // synchronously, so a failure there meant the message call never fired and
  // the typed sentence was silently dropped — already cleared from the box. On
  // success the optimistic bubble was re-appended *after* the upload's reply,
  // so the user's own words visibly jumped below the answer to them.
  const send = (text, files = []) =>
    run(async () => {
      const trimmed = (text || "").trim();
      if (!trimmed && files.length === 0) return null;

      const localIds = [];
      const optimistic = [];
      if (files.length) {
        const id = `local-files-${Date.now()}`;
        localIds.push(id);
        optimistic.push({
          message_id: id,
          role: "user",
          kind: "files",
          content: {
            text: "",
            files: files.map((f) => ({
              filename: f.name,
              name: f.name,
              size: f.size,
              status: "uploading",
            })),
          },
        });
      }
      if (trimmed) {
        const id = `local-user-${Date.now()}`;
        localIds.push(id);
        optimistic.push({
          message_id: id,
          role: "user",
          kind: "text",
          content: { text: trimmed },
        });
      }
      setMessages((prior) => [...prior, ...optimistic]);

      const body = await api.sendTurn(chatId, trimmed, files);
      // Swap every optimistic bubble for the server's stored turn, in order.
      setMessages((prior) => [
        ...prior.filter((m) => !localIds.includes(m.message_id)),
        ...(body.messages ?? []),
      ]);
      if (body.chat) setChat(body.chat);

      await refreshChats();
    });

  const handleAction = (action) =>
    run(async () => {
      if (action.type === "say") {
        return send(action.text);
      }

      if (action.type === "resolve") {
        const analysis = await api.resolveConflicts(sessionId, {
          [action.conflictId]: action.choice,
        });
        // Update the conflict card in place with the backend's authoritative
        // resolution, so the chosen option is highlighted and the card shows as
        // resolved right where the user is. Appending a "Recorded" turn instead
        // both lost the highlight and scrolled the user to the bottom of the
        // chat — the bug this fixes.
        const resolved = new Map(
          (analysis.conflicts ?? []).map((c) => [c.conflict_id, c]),
        );
        setMessages((prior) => prior.map((m) => withResolved(m, resolved)));
        return null;
      }

      if (action.type === "fill") {
        // Returned to the panel so it can show the outcome inline: a rejected
        // value ("that is not a date I can read") is feedback the user needs
        // next to the box they typed in, not as a new turn further down.
        return api.fillIssue(sessionId, action.issueId, action.value);
      }

      if (action.type === "edit_cell") {
        // Returned to the table so a rejection lands next to the cell that
        // caused it. On success the whole report has been re-planned from the
        // updated model, so the preview is refreshed from the response rather
        // than patched — the two must not be able to disagree.
        const body = await api.editCell(sessionId, action);
        if (body.applied) {
          setMessages((prior) => withRefreshedPreview(prior, body));
        }
        return body;
      }

      if (action.type === "edit_prose") {
        // A rewritten card. Like edit_cell, the whole report is re-planned from
        // the override, so the preview is refreshed from the response rather
        // than patched — the two must not be able to disagree. A rejected value
        // (a figure the report doesn't hold) lands back next to the editor.
        const body = await api.editProse(sessionId, action);
        if (body.applied) {
          setMessages((prior) => withRefreshedPreview(prior, body));
        }
        return body;
      }

      if (action.type === "generate") {
        const body = await api.generateAs(sessionId, action.format, true);
        const unresolved = body.generated_with_unresolved_conflicts ?? [];
        setMessages((prior) => [
          ...prior,
          {
            message_id: `local-dl-${Date.now()}`,
            role: "agent",
            kind: "text",
            content: {
              format: "markdown",
              content:
                `Here is the ${action.format}.` +
                (unresolved.length
                  ? ` It carries ${unresolved.length} unresolved critical conflict(s), and says so.`
                  : ""),
              artifacts: (body.outputs ?? []).map((name) => ({
                filename: name,
                session_id: sessionId,
                type: extensionOf(name),
                title: name,
                status: "ready",
                download_url: api.downloadUrl(sessionId, name),
              })),
              actions: [],
              status: "completed",
            },
          },
        ]);
        return null;
      }

      return null;
    });

  const rename = (id, title) =>
    run(async () => {
      await api.patchChat(id, { title });
      await refreshChats();
    });

  const archive = (id, archived) =>
    run(async () => {
      await api.patchChat(id, { archived });
      const remaining = await refreshChats();
      if (archived && id === chatId) {
        if (remaining.length) openChat(remaining[0].chat_id);
        else newChat();
      }
    });

  const remove = (id, title) =>
    run(async () => {
      // Deleting drops the conversation; the uploaded files and the analysis
      // survive on the server. Still worth confirming — it is the only handle
      // the user has on a week's material.
      if (!window.confirm(`Delete “${title}”? The conversation is removed.`)) {
        return;
      }
      await api.deleteChat(id);
      const remaining = await refreshChats();
      if (id === chatId) {
        if (remaining.length) openChat(remaining[0].chat_id);
        else newChat();
      }
    });

  return (
    <div className="flex h-screen bg-slate-50">
      <Sidebar
        chats={chats}
        projects={projects}
        activeChatId={activeProject ? null : chatId}
        activeProjectId={activeProject?.project_id}
        onNew={newChat}
        onOpen={openChat}
        onRename={rename}
        onArchive={archive}
        onDelete={remove}
        onOpenProject={openProject}
        onCreateProject={createProject}
        onRenameProject={renameProject}
        onChangeProjectIcon={changeProjectIcon}
        onDeleteProject={deleteProject}
        onMoveChat={moveChatToProject}
        busy={busy}
      />

      {activeProject ? (
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-1 border-b border-slate-200
                          bg-white px-6 py-2">
            <span className="mr-2 text-lg">{activeProject.icon || "📁"}</span>
            <span className="mr-3 truncate text-sm font-semibold text-slate-800">
              {activeProject.name}
            </span>
            <TabButton active={projectTab === "workspace"}
                       onClick={() => setProjectTab("workspace")}>
              Workspace
            </TabButton>
            <TabButton active={projectTab === "knowledge"}
                       onClick={() => setProjectTab("knowledge")}>
              Knowledge &amp; chats
            </TabButton>
          </div>

          {error && (
            <div className="border-b border-rag-red/30 bg-red-50 px-6 py-2 text-sm
                            text-rag-red">
              {error}
            </div>
          )}

          {projectTab === "workspace" ? (
            <main className="flex min-h-0 flex-1 flex-col bg-slate-50">
              <ProjectWorkspace
                messages={wsMessages}
                draft={wsDraft}
                versions={wsVersions}
                knowledgeVersion={wsKnowledge.version}
                staleCount={wsStale}
                hasKnowledge={wsKnowledge.exists}
                busy={busy}
                onUploadFiles={wsUpload}
                onSend={wsSend}
                onCreateDraft={wsCreateDraft}
                onSaveSection={wsSaveSection}
                onRegenerate={wsRegenerate}
                onExport={wsExport}
                onLoadVersions={wsLoadVersions}
                onRestore={wsRestore}
              />
            </main>
          ) : (
            <ProjectPanel
              project={activeProject}
              chats={chats.filter((c) => c.project_id === activeProject.project_id)}
              availableChats={chats.filter((c) => !c.project_id)}
              busy={busy}
              onSaveKnowledge={(text) =>
                saveProjectKnowledge(activeProject.project_id, text)
              }
              onNewChat={() => newChat(activeProject.project_id)}
              onAddExistingChat={(existingChatId) =>
                addExistingChat(activeProject.project_id, existingChatId)
              }
              onAddRule={(rule) =>
                addProjectRule(activeProject.project_id, rule)
              }
              onOpenChat={openChat}
              onChangeIcon={(icon) =>
                changeProjectIcon(activeProject.project_id, icon)
              }
              onRename={(name) => renameProject(activeProject.project_id, name)}
            />
          )}
        </div>
      ) : (
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b
                           border-slate-200 bg-white px-6 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="max-w-72 truncate text-sm font-semibold text-slate-900">
              {chat?.title || "New chat"}
            </h1>
            <ChatProjectPicker
              chat={chat}
              projects={projects}
              busy={busy}
              onChange={(projectId) => moveChatToProject(chatId, projectId)}
            />
          </div>
          <ModelPicker
            chat={chat}
            busy={busy}
            onChange={(choice) =>
              run(async () => {
                const body = await api.patchChat(chatId, choice);
                setChat(body.chat);
              })
            }
          />
        </header>

        {error && (
          <div className="border-b border-rag-red/30 bg-red-50 px-6 py-2 text-sm
                          text-rag-red">
            {error}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mx-auto max-w-3xl space-y-4">
            {messages.map((message) => (
              <MessageBubble
                key={message.message_id}
                message={message}
                onAction={handleAction}
                busy={busy}
              />
            ))}
            {/* Sits where the reply will appear, so the eye is already there. */}
            <Thinking active={busy} />
            <div ref={bottom} />
          </div>
        </div>

        <Composer
          onSend={send}
          onStop={stop}
          busy={busy}
          disabled={!chatId}
        />
      </main>
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "bg-slate-900 text-white"
          : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
      }`}
    >
      {children}
    </button>
  );
}

// A workspace turn from /api/chat: the agent's Markdown reply, with any download
// actions resolved to a URL so the bubble can offer the file directly.
function wsAgentTurn(projectId, resp) {
  const actions = (resp.actions || []).map((a) =>
    a.type === "download" && a.file
      ? { ...a, url: api.exportDownloadUrl(projectId, a.file) }
      : a,
  );
  return { id: `a-${Date.now()}`, role: "agent", text: resp.message || "", actions };
}

function wsTurn(text) {
  return { id: `s-${Date.now()}`, role: "agent", text };
}

function agentSays(text, kind = "text") {
  return {
    message_id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role: "agent",
    kind,
    content: { text },
  };
}

// Overlay the re-planned content a cell/prose edit returned onto the preview the
// user is looking at — the most recent one. Matching by an exact `version - 1`
// offset used to drop the update whenever the stored content had advanced by
// more than one version since that preview was shown (a re-plan in between), so
// the table kept the old value and the edit read as "not saved". The whole
// re-planned content comes back in the response, so refreshing the last preview
// is both correct and can't disagree with the deck.
/**
 * An edit re-plans the whole report, so the newest draft offer has to point at
 * the new version. Only the version moves: the panel fetches the document
 * itself, which is what stops the chat and the artifact from disagreeing.
 */
function withRefreshedPreview(messages, body) {
  let target = -1;
  messages.forEach((message, index) => {
    if ((message.content?.actions ?? []).some((a) => a.type === "open_preview")) {
      target = index;
    }
  });
  if (target === -1) return messages;
  return messages.map((message, index) =>
    index === target
      ? {
          ...message,
          content: {
            ...message.content,
            actions: message.content.actions.map((a) =>
              a.type === "open_preview" ? { ...a, version: body.version } : a,
            ),
          },
        }
      : message,
  );
}

/** Fold a resolution back into whichever answer offered the choice. */
function withResolved(message, resolved) {
  const actions = message.content?.actions ?? [];
  if (!actions.some((a) => a.type === "resolve_conflict")) return message;
  return {
    ...message,
    content: {
      ...message.content,
      actions: actions.map((a) =>
        a.type === "resolve_conflict"
          ? {
              ...a,
              conflicts: (a.conflicts ?? []).map(
                (c) => resolved.get(c.conflict_id) ?? c,
              ),
            }
          : a,
      ),
    },
  };
}

function extensionOf(name) {
  const ext = String(name).split(".").pop()?.toLowerCase();
  return ["pptx", "docx", "pdf", "xlsx", "html", "png", "md"].includes(ext)
    ? ext
    : "other";
}

function userSays(text) {
  return {
    message_id: `local-user-${Date.now()}`,
    role: "user",
    kind: "text",
    content: { text },
  };
}
