import { useEffect, useRef, useState } from "react";

import * as api from "./api";
import Composer from "./components/chat/Composer";
import MessageBubble from "./components/chat/MessageBubble";
import ModelPicker from "./components/chat/ModelPicker";
import ProjectPanel from "./components/chat/ProjectPanel";
import Sidebar from "./components/chat/Sidebar";
import Thinking from "./components/chat/Thinking";

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
      setError(e.message);
      return null;
    } finally {
      setBusy(false);
    }
  };

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

  // One turn = optional attachments + optional prompt. Files are uploaded first
  // so `respond()` sees them on disk, then the prompt is sent as a single
  // request — this is what lets a user drop the trackers and say what they want
  // in the same message.
  const send = (text, files = []) =>
    run(async () => {
      const trimmed = (text || "").trim();
      if (!trimmed && files.length === 0) return null;

      const filesBubbleId = `local-files-${Date.now()}`;
      const userMsgId = `local-user-${Date.now()}`;

      // Show the user's turn immediately; the server assigns the real ids.
      setMessages((prior) => [
        ...prior,
        ...(files.length
          ? [
              {
                message_id: filesBubbleId,
                role: "user",
                kind: "files",
                content: { files: files.map((f) => ({ name: f.name })) },
              },
            ]
          : []),
        ...(trimmed
          ? [{ message_id: userMsgId, role: "user", kind: "text", content: { text: trimmed } }]
          : []),
      ]);

      if (files.length) {
        // Posted to the chat, not to the bare upload endpoint: the upload is a
        // turn with an answer. It used to be a silent side effect, so the "N
        // files ready" line was invented here and vanished on reopen, and
        // nothing server-side re-read anything.
        const body = await api.addChatFiles(chatId, files);
        setMessages((prior) => [
          ...prior.map((m) =>
            m.message_id === filesBubbleId
              ? { ...m, content: { files: (body.saved ?? []).map((n) => ({ name: n })) } }
              : m,
          ),
          ...(body.messages ?? []),
        ]);
      }

      if (trimmed) {
        const body = await api.sendMessage(chatId, trimmed);
        // Swap the optimistic prose bubble for the server's stored turn(s).
        setMessages((prior) => [
          ...prior.filter((m) => m.message_id !== userMsgId),
          ...body.messages,
        ]);
      }

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
        setMessages((prior) =>
          prior.map((m) =>
            m.kind === "conflict"
              ? {
                  ...m,
                  content: {
                    ...m.content,
                    conflicts: (m.content.conflicts ?? []).map(
                      (c) => resolved.get(c.conflict_id) ?? c,
                    ),
                  },
                }
              : m,
          ),
        );
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
        setMessages((prior) => [
          ...prior,
          {
            message_id: `local-dl-${Date.now()}`,
            role: "agent",
            kind: "downloads",
            content: {
              text: "Done.",
              session_id: sessionId,
              outputs: body.outputs ?? [],
              summary: body.summary ?? [],
              unresolved: body.generated_with_unresolved_conflicts ?? [],
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
        busy={busy}
      />

      {activeProject ? (
        <ProjectPanel
          project={activeProject}
          chats={chats.filter((c) => c.project_id === activeProject.project_id)}
          busy={busy}
          onSaveKnowledge={(text) =>
            saveProjectKnowledge(activeProject.project_id, text)
          }
          onNewChat={() => newChat(activeProject.project_id)}
          onOpenChat={openChat}
          onChangeIcon={(icon) =>
            changeProjectIcon(activeProject.project_id, icon)
          }
          onRename={(name) => renameProject(activeProject.project_id, name)}
        />
      ) : (
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b
                           border-slate-200 bg-white px-6 py-3">
          <div>
            <h1 className="text-sm font-semibold text-slate-900">
              PMI Reporting Agent
            </h1>
            <p className="text-xs text-slate-500">
              Every figure traced to the file it came from.
            </p>
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
          busy={busy}
          disabled={!chatId}
        />
      </main>
      )}
    </div>
  );
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
function withRefreshedPreview(messages, body) {
  let target = -1;
  messages.forEach((message, index) => {
    if (message.kind === "preview") target = index;
  });
  if (target === -1) return messages;
  return messages.map((message, index) =>
    index === target
      ? {
          ...message,
          content: {
            ...message.content,
            version: body.version,
            markdown: body.markdown,
            sections: body.blocks,
          },
        }
      : message,
  );
}

function userSays(text) {
  return {
    message_id: `local-user-${Date.now()}`,
    role: "user",
    kind: "text",
    content: { text },
  };
}
