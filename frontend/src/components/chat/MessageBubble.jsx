import { useState } from "react";

import ConflictCard from "../ConflictCard";
import LowConfidencePanel from "../LowConfidencePanel";
import Attachments from "./Attachments";
import Artifacts from "./Artifacts";
import Markdown from "./Markdown";
import PreviewPanel from "./PreviewPanel";

/**
 * One turn in the transcript.
 *
 * The agent's reply is **prose**. It used to be a card: the component switched
 * on `kind` and rendered a conflict panel, a preview or a download set, which
 * meant the assistant could only ever say something the card vocabulary had a
 * slot for. Anything else — an explanation, a comparison, a plain answer to a
 * plain question — had nowhere to go.
 *
 * What survives from the cards is the *affordances*. Resolving a conflict with
 * one click is genuinely better than typing "use the 82 from the tracker", so
 * the control stays; it just sits under the answer instead of being it. Same for
 * the draft: the prose says what the report argues, and the panel opens on
 * request.
 */
export default function MessageBubble({ message, onAction, busy }) {
  const { role, content } = message;

  if (role === "user") {
    return (
      <div className="flex flex-col items-end gap-1.5">
        {content.text && (
          <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5
                          text-sm text-white">
            {content.text}
          </div>
        )}
        {/* The files went with *this* message. Rendering them from the stored
            message rather than from local state is what makes them survive a
            reload — and what stops an upload-only turn rendering as an empty
            black pill, which is all the user used to see. */}
        <Attachments files={content.files} />
      </div>
    );
  }

  const failed = content.status === "failed";

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-2">
        {content.content && (
          <div
            className={
              failed
                ? "rounded-2xl rounded-bl-sm border border-rag-amber/50 bg-amber-50/60 px-4 py-2.5 text-sm text-slate-800"
                : "rounded-2xl rounded-bl-sm bg-white px-4 py-2.5 text-sm text-slate-800 shadow-sm ring-1 ring-slate-200"
            }
          >
            <Markdown source={content.content} />
          </div>
        )}

        <Artifacts artifacts={content.artifacts} />

        {(content.actions ?? []).map((action, index) => (
          <ActionControl
            key={`${action.type}-${index}`}
            action={action}
            onAction={onAction}
            busy={busy}
          />
        ))}
      </div>
    </div>
  );
}

/** An offer, never the answer. Each renders under the prose it belongs to. */
function ActionControl({ action, onAction, busy }) {
  switch (action.type) {
    case "resolve_conflict":
      return (
        <div className="space-y-2">
          {(action.conflicts ?? []).map((conflict) => (
            <ConflictCard
              key={conflict.conflict_id}
              conflict={conflict}
              busy={busy}
              onResolve={(conflictId, choice) =>
                onAction({ type: "resolve", conflictId, choice })
              }
            />
          ))}
        </div>
      );

    case "choose_audience":
      return <AudienceChoice action={action} onAction={onAction} busy={busy} />;

    case "choose_format":
      return <FormatChoice action={action} onAction={onAction} busy={busy} />;

    case "review_low_confidence":
      return <LowConfidencePanel items={action.items ?? []} />;

    case "open_preview":
      return <PreviewPanel action={action} onAction={onAction} busy={busy} />;

    default:
      return null;
  }
}

function FormatChoice({ action, onAction, busy }) {
  return (
    <div className="flex flex-wrap gap-2">
      {(action.options ?? []).map((option) => (
        <button
          key={option}
          type="button"
          disabled={busy}
          onClick={() => onAction({ type: "say", text: FORMAT_LABELS[option] ?? option })}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs
                     font-medium text-slate-700 hover:border-slate-500
                     disabled:opacity-40"
        >
          {FORMAT_LABELS[option] ?? option}
        </button>
      ))}
    </div>
  );
}

const FORMAT_LABELS = {
  powerpoint: "PowerPoint",
  pdf: "PDF",
  word: "Word",
  html: "HTML",
  chart: "Chart",
};

/**
 * §4's audience question — open, with the four report shapes as examples.
 *
 * The chips used to be the whole answer, so somebody who wanted a pack for the
 * Integration Director had to pick the closest-looking one, and that label then
 * went on the title page. Anything typed here is matched to a report shape by
 * the backend and kept verbatim as the document's audience label.
 *
 * The chips stay unselected until clicked: the agent is asking because it could
 * not infer, and a preselected default defeats the ask.
 */
function AudienceChoice({ action, onAction, busy }) {
  const [custom, setCustom] = useState("");
  const submit = () => {
    const value = custom.trim();
    if (!value || busy) return;
    setCustom("");
    onAction({ type: "say", text: value });
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {(action.options ?? []).map((option) => (
          <button
            key={option}
            type="button"
            disabled={busy}
            onClick={() => onAction({ type: "say", text: option })}
            className="rounded-full border border-slate-300 bg-white px-3 py-1.5
                       text-sm text-slate-700 hover:border-slate-500
                       disabled:opacity-40"
          >
            {option}
          </button>
        ))}
      </div>

      {action.free_text && (
        <div className="flex gap-2">
          <input
            type="text"
            value={custom}
            disabled={busy}
            placeholder={action.placeholder ?? "…or say who in your own words"}
            onChange={(event) => setCustom(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && submit()}
            className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm
                       text-slate-800 placeholder:text-slate-400
                       focus:border-slate-500 focus:outline-none disabled:opacity-40"
          />
          <button
            type="button"
            disabled={busy || !custom.trim()}
            onClick={submit}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm
                       font-medium text-slate-700 hover:border-slate-500
                       disabled:opacity-40"
          >
            Use this
          </button>
        </div>
      )}
    </div>
  );
}
