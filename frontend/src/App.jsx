import { useEffect, useRef, useState } from "react";

import * as api from "./api";
import Composer from "./components/chat/Composer";
import MessageBubble from "./components/chat/MessageBubble";
import ModelPicker from "./components/chat/ModelPicker";
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

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottom = useRef(null);

  useEffect(() => {
    refreshChats().then((existing) => {
      if (existing.length) openChat(existing[0].chat_id);
      else newChat();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

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

  const newChat = () =>
    run(async () => {
      const body = await api.createChat({ title: "New chat" });
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
      setChatId(id);
      setChat(body.chat);
      setSessionId(body.chat.session_id);
      setMessages(body.messages);
    });

  const send = (text) =>
    run(async () => {
      // Show the user's turn immediately; the server assigns the real id.
      setMessages((prior) => [...prior, userSays(text)]);
      const body = await api.sendMessage(chatId, text);
      setMessages((prior) => [...prior.slice(0, -1), ...body.messages]);
      await refreshChats();
    });

  const upload = (files) =>
    run(async () => {
      const body = await api.uploadFiles(sessionId, files);
      setMessages((prior) => [
        ...prior,
        {
          message_id: `local-files-${Date.now()}`,
          role: "user",
          kind: "files",
          content: { files: body.files },
        },
        ...(body.rejected?.length
          ? [
              agentSays(
                `I couldn't read: ${body.rejected
                  .map((r) => r.name ?? r)
                  .join(", ")}.`,
                "notice",
              ),
            ]
          : []),
        agentSays(
          `${body.files.length} file(s) ready. What do you need — a SteerCo ` +
            "deck, an IMO status report, a Finance dashboard?",
        ),
      ]);
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
        setMessages((prior) => [
          ...prior,
          agentSays(
            `Recorded. ${analysis.unresolved_conflicts?.length ?? 0} conflict(s) ` +
              "still open. Ask me to re-plan so the draft matches.",
          ),
        ]);
        return null;
      }

      if (action.type === "fill") {
        // Returned to the panel so it can show the outcome inline: a rejected
        // value ("that is not a date I can read") is feedback the user needs
        // next to the box they typed in, not as a new turn further down.
        return api.fillIssue(sessionId, action.issueId, action.value);
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
        activeChatId={chatId}
        onNew={newChat}
        onOpen={openChat}
        onRename={rename}
        onArchive={archive}
        onDelete={remove}
        busy={busy}
      />

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
          onUpload={upload}
          busy={busy}
          disabled={!chatId}
        />
      </main>
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

function userSays(text) {
  return {
    message_id: `local-user-${Date.now()}`,
    role: "user",
    kind: "text",
    content: { text },
  };
}
