import { useState } from "react";

/**
 * Chat history: new, open, rename, close.
 *
 * "Close" archives rather than deletes, and delete is a separate, confirmed
 * action — because a chat is the only handle a user has on a week's worth of
 * uploaded files, and losing it by mis-clicking would be expensive.
 */
export default function Sidebar({
  chats,
  activeChatId,
  onNew,
  onOpen,
  onRename,
  onArchive,
  onDelete,
  busy,
}) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");

  const startRename = (chat) => {
    setEditingId(chat.chat_id);
    setDraft(chat.title);
  };

  const commitRename = (chatId) => {
    const title = draft.trim();
    if (title) onRename(chatId, title);
    setEditingId(null);
  };

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          disabled={busy}
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium
                     text-white hover:bg-slate-700 disabled:opacity-40"
        >
          + New chat
        </button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {chats.length === 0 && (
          <p className="px-2 py-6 text-center text-xs text-slate-400">
            No chats yet.
          </p>
        )}

        {chats.map((chat) => {
          const active = chat.chat_id === activeChatId;
          return (
            <div
              key={chat.chat_id}
              className={`group mb-1 rounded-lg px-2 py-2 text-sm transition
                ${active ? "bg-slate-100" : "hover:bg-slate-50"}`}
            >
              {editingId === chat.chat_id ? (
                <input
                  autoFocus
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onBlur={() => commitRename(chat.chat_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") commitRename(chat.chat_id);
                    if (event.key === "Escape") setEditingId(null);
                  }}
                  className="w-full rounded border border-slate-300 px-1.5 py-1
                             text-sm focus:border-slate-500 focus:outline-none"
                />
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => onOpen(chat.chat_id)}
                    className="block w-full truncate text-left font-medium text-slate-800"
                    title={chat.title}
                  >
                    {chat.title}
                  </button>

                  <div className="mt-0.5 flex items-center justify-between">
                    <span className="text-[11px] text-slate-400">
                      {chat.message_count} message
                      {chat.message_count === 1 ? "" : "s"}
                    </span>

                    {/* Revealed on hover so the list stays readable, but kept
                        in the DOM so they remain keyboard-reachable. */}
                    <span className="flex gap-1 opacity-0 transition group-hover:opacity-100
                                     focus-within:opacity-100">
                      <IconButton label="Rename" onClick={() => startRename(chat)}>
                        ✎
                      </IconButton>
                      {/* 
                      <IconButton
                        label={chat.archived_at ? "Reopen" : "Close"}
                        onClick={() => onArchive(chat.chat_id, !chat.archived_at)}
                      >
                        {chat.archived_at ? "↺" : "×"}
                      </IconButton>*/}
                      <IconButton
                        label="Delete"
                        onClick={() => onDelete(chat.chat_id, chat.title)}
                      >
                        🗑
                      </IconButton>
                    </span>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}

function IconButton({ label, onClick, children }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="rounded px-1 text-xs text-slate-400 hover:bg-slate-200 hover:text-slate-700"
    >
      {children}
    </button>
  );
}
