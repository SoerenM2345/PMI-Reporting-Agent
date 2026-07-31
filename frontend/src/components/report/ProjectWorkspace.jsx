import { useRef, useState } from "react";

import Markdown from "../chat/Markdown";
import EditableReport from "./EditableReport";
import StatusPill from "./StatusPill";

/**
 * The project workspace (spec §"API Direction", §"Frontend Requirements").
 *
 * The continuously-updating flow, end to end: drop files (each becomes a source
 * and the knowledge base re-derives), talk to the agent in plain language
 * (`/api/chat`, replies rendered as Markdown — not cards), and read/edit the
 * report as free text on the right, exporting only when asked.
 *
 * Presentational: all state and every backend call live in App.jsx, per the
 * app's conventions. Downloads are surfaced as a normal link card — one of the
 * few things a card is still right for.
 */
export default function ProjectWorkspace({
  messages = [],
  draft,
  versions = [],
  knowledgeVersion,
  staleCount = 0,
  hasKnowledge = false,
  busy = false,
  onUploadFiles,
  onSend,
  onCreateDraft,
  onSaveSection,
  onRegenerate,
  onExport,
  onLoadVersions,
  onRestore,
}) {
  const [text, setText] = useState("");
  const fileInput = useRef(null);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend?.(trimmed);
    setText("");
  };

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4
                    lg:grid-cols-2">
      {/* --------------------------------------------------- conversation */}
      <div className="flex min-h-0 flex-col rounded-2xl border border-slate-200
                      bg-white">
        <div className="flex items-center justify-between gap-3 border-b
                        border-slate-100 px-4 py-3">
          <StatusPill knowledgeVersion={knowledgeVersion} staleCount={staleCount} />
          <div>
            <input ref={fileInput} type="file" multiple hidden
                   onChange={(e) => {
                     const files = Array.from(e.target.files || []);
                     if (files.length) onUploadFiles?.(files);
                     e.target.value = "";
                   }} />
            <button type="button" onClick={() => fileInput.current?.click()}
                    disabled={busy}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5
                               text-xs font-semibold text-slate-700 hover:bg-slate-50
                               disabled:opacity-40">
              ＋ Add files
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <p className="text-sm text-slate-400">
              Add the project's files, then ask for what you need — “create an
              executive SteerCo report”, “what are the main concerns?”, or tell me
              a correction like “ERP go-live is now 15-09-2026”.
            </p>
          )}
          {messages.map((m) => (
            <Turn key={m.id} message={m} onExport={onExport} />
          ))}
        </div>

        <div className="border-t border-slate-100 p-3">
          <div className="flex items-end gap-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={2}
              placeholder="Message the project…"
              disabled={busy}
              className="min-h-0 flex-1 resize-none rounded-xl border border-slate-200
                         px-3 py-2 text-sm outline-none focus:border-slate-400"
            />
            <button type="button" onClick={submit} disabled={busy || !text.trim()}
                    className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold
                               text-white hover:bg-slate-700 disabled:opacity-40">
              Send
            </button>
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------- report */}
      <div className="min-h-0 overflow-y-auto">
        {draft ? (
          <EditableReport
            draft={draft}
            versions={versions}
            busy={busy}
            onSaveSection={onSaveSection}
            onRegenerate={onRegenerate}
            onExport={onExport}
            onLoadVersions={onLoadVersions}
            onRestore={onRestore}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center rounded-2xl
                          border border-dashed border-slate-200 bg-white px-6 py-10
                          text-center">
            <p className="mb-3 text-sm text-slate-500">
              No report drafted yet.
            </p>
            <button type="button" onClick={onCreateDraft}
                    disabled={busy || !hasKnowledge}
                    className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold
                               text-white hover:bg-slate-700 disabled:opacity-40">
              Draft a report
            </button>
            {!hasKnowledge && (
              <p className="mt-2 text-xs text-slate-400">
                Add files first — there's nothing to draft from yet.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Turn({ message, onExport }) {
  const isUser = message.role === "user";
  const downloads = (message.actions || []).filter((a) => a.type === "download");
  return (
    <div className={isUser ? "flex justify-end" : ""}>
      <div className={`max-w-[92%] rounded-2xl px-3 py-2 ${
        isUser ? "bg-slate-900 text-white" : "bg-slate-50 text-slate-800"}`}>
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.text}</p>
        ) : (
          <Markdown source={message.text} />
        )}
        {downloads.map((d) => (
          <a key={d.file} href={d.url} download
             className="mt-2 inline-block rounded-lg border border-slate-300 bg-white
                        px-3 py-1.5 text-xs font-semibold text-slate-700
                        hover:bg-slate-50">
            ⬇ {d.file}
          </a>
        ))}
      </div>
    </div>
  );
}
