import { useEffect, useState } from "react";

/**
 * The main pane when a project is open (App.jsx swaps this in for the chat).
 *
 * A project is a folder over chats plus a scratchpad of standing knowledge —
 * background, glossary, instructions the user wants to keep next to a body of
 * work. This is where that text is edited; the sidebar handles filing and the
 * chats themselves are opened from here or from the sidebar tree.
 *
 * Knowledge is edited against a local draft and saved explicitly, so a
 * half-typed note is never persisted and the Save button can show whether there
 * is anything to save. Every write still goes through App's `run(fn)`.
 */
const PROJECT_ICONS = [
  "📁", "📊", "🚀", "🏢", "💼", "🧠", "⚙️", "🔍", "📝", "🎯",
];

export default function ProjectPanel({
  project,
  chats = [],
  busy = false,
  onSaveKnowledge,
  onNewChat,
  onOpenChat,
  onChangeIcon,
  onRename,
}) {
  const [draft, setDraft] = useState(project.knowledge || "");
  const [showIcons, setShowIcons] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(project.name);

  // Reset local state whenever a different project is opened, or the saved
  // knowledge changes underneath (e.g. after a successful save re-reads it).
  useEffect(() => {
    setDraft(project.knowledge || "");
    setNameDraft(project.name);
    setShowIcons(false);
    setEditingName(false);
  }, [project.project_id, project.knowledge, project.name]);

  const dirty = draft !== (project.knowledge || "");

  const commitName = () => {
    const name = nameDraft.trim();
    if (name && name !== project.name) onRename?.(name);
    setEditingName(false);
  };

  return (
    <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowIcons((v) => !v)}
              title="Change project icon"
              aria-label="Change project icon"
              className="flex h-11 w-11 items-center justify-center rounded-xl
                         border border-slate-200 bg-slate-50 text-2xl
                         transition hover:bg-slate-100"
            >
              {project.icon || "📁"}
            </button>

            {showIcons && (
              <div
                className="absolute left-0 top-full z-20 mt-2 w-56 rounded-xl
                           border border-slate-200 bg-white p-2 shadow-lg"
              >
                <div className="grid grid-cols-5 gap-1">
                  {PROJECT_ICONS.map((icon) => (
                    <button
                      key={icon}
                      type="button"
                      onClick={() => {
                        onChangeIcon?.(icon);
                        setShowIcons(false);
                      }}
                      className={`flex h-9 w-9 items-center justify-center
                                  rounded-lg text-lg transition hover:bg-slate-100
                                  ${
                                    project.icon === icon
                                      ? "bg-slate-200 ring-1 ring-slate-300"
                                      : ""
                                  }`}
                    >
                      {icon}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1">
            {editingName ? (
              <input
                autoFocus
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={commitName}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitName();
                  if (e.key === "Escape") {
                    setNameDraft(project.name);
                    setEditingName(false);
                  }
                }}
                className="w-full rounded-lg border border-slate-300 bg-white
                           px-2 py-1 text-lg font-semibold text-slate-900
                           outline-none focus:border-slate-500"
              />
            ) : (
              <button
                type="button"
                onClick={() => setEditingName(true)}
                title="Rename project"
                className="truncate text-left text-lg font-semibold text-slate-900
                           hover:text-slate-600"
              >
                {project.name}
              </button>
            )}
            <p className="text-xs text-slate-500">
              Project knowledge — kept next to every chat filed here.
            </p>
          </div>

          <button
            type="button"
            onClick={onNewChat}
            disabled={busy}
            className="shrink-0 rounded-lg bg-slate-900 px-3 py-2 text-sm
                       font-semibold text-white transition hover:bg-slate-700
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            ＋ New chat
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-6">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800">
                Knowledge &amp; context
              </h2>
              <button
                type="button"
                onClick={() => onSaveKnowledge?.(draft)}
                disabled={busy || !dirty}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5
                           text-xs font-semibold text-slate-700 transition
                           hover:bg-slate-50 disabled:cursor-not-allowed
                           disabled:opacity-40"
              >
                {dirty ? "Save" : "Saved"}
              </button>
            </div>

            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={
                "Background, glossary, standing instructions… anything you want " +
                "kept alongside this project's chats."
              }
              rows={12}
              className="w-full resize-y rounded-xl border border-slate-200
                         bg-white px-4 py-3 text-sm leading-relaxed text-slate-800
                         outline-none placeholder:text-slate-400
                         focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            />
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold text-slate-800">
              Chats in this project
            </h2>

            {chats.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-200
                            bg-white px-4 py-6 text-center text-sm text-slate-400">
                No chats yet. Start one with “New chat” above.
              </p>
            ) : (
              <ul className="space-y-1">
                {chats.map((chat) => (
                  <li key={chat.chat_id}>
                    <button
                      type="button"
                      onClick={() => onOpenChat?.(chat.chat_id)}
                      className="flex w-full items-center justify-between
                                 rounded-lg border border-slate-200 bg-white
                                 px-4 py-3 text-left transition hover:bg-slate-50"
                    >
                      <span className="truncate text-sm font-medium text-slate-700">
                        {chat.title}
                      </span>
                      <span className="ml-3 shrink-0 text-xs text-slate-400">
                        {chat.message_count || 0} message
                        {chat.message_count === 1 ? "" : "s"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
