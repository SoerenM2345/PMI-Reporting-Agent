import { useEffect, useState } from "react";

import * as api from "../../api";
import PreviewBody from "./PreviewBody";

/**
 * The drafted report, on request.
 *
 * The draft used to be inlined in the transcript: every re-plan put a second
 * copy of the whole document into the conversation, which is most of what
 * `agent/budget.py` then had to compact away. Now the message carries only the
 * session and version, and the document is fetched from the place it already
 * lives — so the chat and the artifact cannot drift, because there is one copy.
 *
 * Collapsed by default. The prose above already says what the report argues;
 * opening it is for checking the figures and editing a cell.
 */
export default function PreviewPanel({ action, onAction, busy }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const sessionId = action.session_id;
  const version = action.version;

  useEffect(() => {
    if (!open || draft) return;
    let live = true;
    api
      .getContent(sessionId)
      .then((body) => live && setDraft(body))
      .catch((err) => live && setError(err.message || "could not load the draft"));
    return () => {
      live = false;
    };
  }, [open, draft, sessionId]);

  // A re-plan means what is on screen is a version behind. Drop it rather than
  // showing an old draft under a current heading.
  useEffect(() => {
    setDraft(null);
  }, [version]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft?.markdown ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access is denied outside a secure context. Saying nothing
      // would leave the button looking like it worked.
      setCopied(false);
    }
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between px-4 py-2">
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          className="text-xs font-medium uppercase tracking-wide text-slate-500
                     hover:text-slate-800"
        >
          {open ? "▾" : "▸"} Draft — version {version}
        </button>
        {open && draft && (
          <button
            type="button"
            onClick={copy}
            className="rounded border border-slate-200 px-2 py-0.5 text-xs
                       text-slate-500 hover:border-slate-400 hover:text-slate-700"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      {open && (
        <div className="max-h-[28rem] overflow-y-auto border-t border-slate-100 px-4 py-3">
          {error && <p className="text-sm text-rag-red">{error}</p>}
          {!error && !draft && (
            <p className="text-sm text-slate-400">Loading the draft…</p>
          )}
          {draft && (
            <PreviewBody
              sections={draft.blocks ?? []}
              busy={busy}
              onEdit={(edit) => onAction({ type: "edit_cell", ...edit })}
              onProseEdit={(edit) => onAction({ type: "edit_prose", ...edit })}
            />
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3">
        <span className="mr-1 text-xs text-slate-500">Generate as</span>
        {(action.formats ?? ["powerpoint"]).map((format) => (
          <button
            key={format}
            type="button"
            disabled={busy}
            onClick={() => onAction({ type: "generate", format })}
            className="rounded border border-slate-300 bg-white px-2.5 py-1 text-xs
                       font-medium text-slate-700 hover:border-slate-500
                       disabled:opacity-40"
          >
            {LABELS[format] ?? format}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-400">
          …or tell me what to change
        </span>
      </div>
    </div>
  );
}

const LABELS = {
  powerpoint: "PowerPoint",
  word: "Word",
  pdf: "PDF",
  html: "HTML",
  excel: "Excel",
  chart: "Charts",
};
