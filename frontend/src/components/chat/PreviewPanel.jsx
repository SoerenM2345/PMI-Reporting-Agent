import { useEffect, useState } from "react";

import * as api from "../../api";
import FormatPreview from "./FormatPreview";

/**
 * The drafted report, on request.
 *
 * The draft used to be inlined in the transcript: every re-plan put a second
 * copy of the whole document into the conversation, which is most of what
 * `agent/budget.py` then had to compact away. Now the message carries only the
 * session and version, and the document is fetched from the place it already
 * lives — so the chat and the artifact cannot drift, because there is one copy.
 *
 * New report drafts open automatically because generation is blocked until the
 * user has reviewed this complete format-specific description. Existing
 * callers can still opt out by omitting `open_by_default`.
 */
export default function PreviewPanel({ action, onAction, busy }) {
  const [open, setOpen] = useState(Boolean(action.open_by_default));
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [approvalError, setApprovalError] = useState("");

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
            <FormatPreview
              preview={draft.format_preview}
              busy={busy}
              onEdit={(edit) => onAction({ type: "edit_cell", ...edit })}
              onProseEdit={(edit) => onAction({ type: "edit_prose", ...edit })}
            />
          )}
        </div>
      )}

      {draft?.review_question && (
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
          {draft.review_question}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3">
        <span className="mr-1 text-xs text-slate-500">
          Output: {LABELS[draft?.selected_format ?? action.selected_format] ?? draft?.selected_format}
        </span>
        <button
          type="button"
          disabled={busy || !draft || draft.stale}
          onClick={async () => {
            setApprovalError("");
            try {
              await onAction({
                type: "approve_generate",
                format: draft.selected_format,
                version: draft.version,
              });
            } catch (err) {
              setApprovalError(err.message || "could not approve this preview");
            }
          }}
          className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white
                     hover:bg-slate-700 disabled:opacity-40"
        >
          Generate now
        </button>
        <span className="ml-auto text-xs text-slate-400">
          …or describe any change in the chat
        </span>
      </div>
      {draft?.stale && (
        <p className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {draft.stale_reason || "The source data changed. A fresh preview is required."}
        </p>
      )}
      {approvalError && (
        <p className="border-t border-red-200 bg-red-50 px-4 py-2 text-xs text-rag-red">
          {approvalError}
        </p>
      )}
    </div>
  );
}

const LABELS = {
  powerpoint: "PowerPoint",
  word: "Word",
  pdf: "PDF",
  html: "HTML",
  chart: "Chart",
};
