import { useLayoutEffect, useRef, useState } from "react";

import Attachments from "./Attachments";

const ACCEPTED = ".xlsx,.xls,.csv,.pptx,.docx,.pdf,.html,.htm,.png,.jpg,.jpeg";

/**
 * The message box, with file attachment folded into it.
 *
 * Uploading is part of the conversation rather than a separate step: attaching
 * files here is how you say "here is this week's material", and the transcript
 * records it as a turn. Files are *staged*, not uploaded on select — they ride
 * along with the next message, so a user can attach the trackers and say what
 * they want in a single turn.
 *
 * **The text and the attachments are one draft.** They used to be two pieces of
 * state, and the bug that produced was subtle enough to look like magic:
 * attaching a file worked, but only if you had not typed anything yet.
 * `handleFiles` captured the live `FileList` and dereferenced it *inside* the
 * state updater, and React only runs an updater eagerly while the fiber is
 * clean. Once `setText` had run once, the updater was deferred to render — by
 * which time the `onChange` handler had already executed `event.target.value =
 * ""`, emptying the very `FileList` it had handed off. `Array.from(list)`
 * evaluated to `[]`, no chip appeared, and the message sent with no files.
 *
 * So the array is materialised **eagerly**, before any state call, and the
 * updater only ever reads a plain array. Same fix for drag-and-drop, which was
 * broken more reliably: `setDragging(false)` guaranteed a queued update ahead of
 * it, and `dataTransfer.files` is neutered once the drop event finishes.
 */
export default function Composer({ onSend, onStop, busy, disabled }) {
  const [draft, setDraft] = useState({ text: "", attachments: [] });
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const textarea = useRef(null);

  const setText = (text) => setDraft((current) => ({ ...current, text }));

  const addFiles = (list) => {
    // Materialised here, not in the updater. See the note above.
    const incoming = Array.from(list ?? []);
    if (incoming.length === 0) return;
    setDraft((current) => {
      const seen = new Set(
        current.attachments.map((f) => `${f.name}:${f.size}`),
      );
      const next = [...current.attachments];
      for (const file of incoming) {
        if (!seen.has(`${file.name}:${file.size}`)) next.push(file);
      }
      return { ...current, attachments: next };
    });
  };

  useLayoutEffect(() => {
    const element = textarea.current;
    if (!element) return;

    // Reset first so the textarea can also shrink after text is deleted.
    element.style.height = "auto";

    const maxHeight = 160;
    const nextHeight = Math.min(element.scrollHeight, maxHeight);

    element.style.height = `${nextHeight}px`;
    element.style.overflowY =
      element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [draft.text]);

  const removeFile = (target) =>
    setDraft((current) => ({
      ...current,
      attachments: current.attachments.filter((f) => f !== target),
    }));

  const submit = (event) => {
    event?.preventDefault();
    const message = draft.text.trim();
    const files = draft.attachments;
    if ((!message && files.length === 0) || busy) return;
    // Cleared only after the send is handed over, and restored by the caller if
    // it fails: a turn that errored used to lose what the user had typed.
    setDraft({ text: "", attachments: [] });
    Promise.resolve(onSend(message, files)).catch(() => {
      setDraft((current) =>
        current.text || current.attachments.length
          ? current
          : { text: message, attachments: files },
      );
    });
  };

  const staged = draft.attachments.map((file) => ({
    name: file.name,
    size: file.size,
    status: "ready",
  }));

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        // Before `setDragging`, so the FileList is read while it is still live.
        addFiles(event.dataTransfer.files);
        setDragging(false);
      }}
      className={`border-t bg-white p-3 transition
        ${dragging ? "border-slate-900 bg-slate-50" : "border-slate-200"}`}
    >
      {staged.length > 0 && (
        <div className="mx-auto mb-2 max-w-3xl">
          <Attachments
            files={staged}
            compact
            onRemove={(file) =>
              removeFile(
                draft.attachments.find(
                  (f) => f.name === file.name && f.size === file.size,
                ),
              )
            }
          />
        </div>
      )}

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
            addFiles(event.target.files);
            event.target.value = "";
          }}
        />

        <textarea
          ref={textarea}
          rows={1}
          value={draft.text}
          disabled={busy || disabled}
          aria-label="Message"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={
            dragging
              ? "Drop the files here…"
              : "Ask for a report, or tell me what to change…"
          }
          className="min-h-10 max-h-40 flex-1 resize-none overflow-y-hidden rounded-lg
             border border-slate-300 px-3 py-2 text-sm leading-5
             focus:border-slate-500 focus:outline-none disabled:opacity-50"
        />

        {/* Send becomes Stop while a turn is running. One control, because
            there is only ever one thing to do: start it or call it off. */}
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm
                       font-medium text-slate-700 hover:border-slate-500"
          >
            ■ Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={disabled || (!draft.text.trim() && staged.length === 0)}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white
                       hover:bg-slate-700 disabled:opacity-40"
          >
            Send
          </button>
        )}
      </form>

      <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-slate-400">
        Drop trackers, decks, minutes, exports — or screenshots of dashboards.
      </p>
    </div>
  );
}
