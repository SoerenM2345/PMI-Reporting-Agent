import { useRef, useState } from "react";

const ACCEPTED = ".xlsx,.xls,.csv,.pptx,.docx,.pdf,.html,.htm,.png,.jpg,.jpeg";

/**
 * The message box, with file attachment folded into it.
 *
 * Uploading is part of the conversation rather than a separate step: dropping
 * files here is how you say "here is this week's material", and the transcript
 * records it as a turn. That is the main structural difference from the wizard,
 * where upload was step 1 of 4 and could not be revisited.
 */
export default function Composer({ onSend, onUpload, busy, disabled }) {
  const [text, setText] = useState("");
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);

  const submit = (event) => {
    event?.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    onSend(message);
  };

  const handleFiles = (list) => {
    if (list?.length) onUpload(Array.from(list));
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        handleFiles(event.dataTransfer.files);
      }}
      className={`border-t bg-white p-3 transition
        ${dragging ? "border-slate-900 bg-slate-50" : "border-slate-200"}`}
    >
      <form onSubmit={submit} className="mx-auto flex max-w-3xl items-end gap-2">
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={busy}
          title="Attach files"
          aria-label="Attach files"
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600
                     hover:border-slate-500 disabled:opacity-40"
        >
          📎
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />

        <textarea
          rows={1}
          value={text}
          disabled={busy || disabled}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter is a newline. A status update is often
            // one line, and needing a mouse to send it gets old fast.
            if (event.key === "Enter" && !event.shiftKey) submit(event);
          }}
          placeholder={
            dragging
              ? "Drop the files here…"
              : "Ask for a report, or tell me what to change…"
          }
          className="max-h-40 flex-1 resize-y rounded-lg border border-slate-300 px-3 py-2
                     text-sm focus:border-slate-500 focus:outline-none disabled:opacity-50"
        />

        <button
          type="submit"
          disabled={busy || disabled || !text.trim()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white
                     hover:bg-slate-700 disabled:opacity-40"
        >
          {busy ? "…" : "Send"}
        </button>
      </form>

      <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-slate-400">
        Drop trackers, decks, minutes, exports — or screenshots of dashboards.
      </p>
    </div>
  );
}
