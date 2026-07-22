import ConflictCard from "../ConflictCard";
import Downloads from "../Downloads";
import LowConfidencePanel from "../LowConfidencePanel";
import IssuesPanel from "./IssuesPanel";
import Markdown from "./Markdown";

/**
 * One turn in the transcript.
 *
 * A chat message here is not always prose. The agent answers with conflict
 * cards, a report preview, a download set — the same components the wizard
 * used, now addressed by `kind`. That is the whole reason the backend stores a
 * kind alongside the content: a disagreement between two files rendered as a
 * paragraph would lose the thing that makes it actionable, which is *where*
 * each number came from and what it said.
 */
export default function MessageBubble({ message, onAction, busy }) {
  const { role, kind, content } = message;

  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5
                        text-sm text-white">
          {content.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[95%] space-y-2">
        {content.text && kind !== "notice" && (
          <div className="rounded-2xl rounded-bl-sm bg-white px-4 py-2.5 text-sm
                          text-slate-800 shadow-sm ring-1 ring-slate-200">
            {content.text}
          </div>
        )}

        <Body message={message} onAction={onAction} busy={busy} />
      </div>
    </div>
  );
}

function Body({ message, onAction, busy }) {
  const { kind, content } = message;

  switch (kind) {
    case "audience_choice":
      return (
        <div className="flex flex-wrap gap-2">
          {(content.options ?? []).map((option) => (
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
      );

    case "conflict":
      return (
        <div className="space-y-2">
          {(content.conflicts ?? []).map((conflict) => (
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

    case "low_confidence":
      return <LowConfidencePanel items={content.items ?? []} />;

    case "issues":
      return (
        <IssuesPanel
          content={content}
          busy={busy}
          onFill={(issueId, value) =>
            onAction({ type: "fill", issueId, value })
          }
        />
      );

    case "preview":
      return <Preview content={content} onAction={onAction} busy={busy} />;

    case "downloads":
      return (
        <Downloads
          sessionId={content.session_id}
          outputs={content.outputs ?? []}
          summary={content.summary ?? []}
          unresolved={content.unresolved ?? []}
        />
      );

    case "notice":
      return (
        <div className="rounded-lg border border-rag-amber/50 bg-amber-50/60 p-3
                        text-sm text-slate-700">
          <p>{content.text}</p>
          {(content.reasons ?? []).length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">
              {content.reasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
      );

    case "files":
      return (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <ul className="space-y-1">
            {(content.files ?? []).map((file) => (
              <li key={file.name ?? file} className="text-slate-700">
                📎 {file.name ?? file}
              </li>
            ))}
          </ul>
        </div>
      );

    default:
      return null;
  }
}

/**
 * The preview: what the report will say, before anything is generated.
 *
 * Format buttons sit under it rather than in a toolbar, because choosing a
 * format is the *consequence* of approving this text — and re-rendering into a
 * second format reuses the same approved content, so it cannot say anything
 * different.
 */
function Preview({ content, onAction, busy }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100
                      px-4 py-2">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Draft — version {content.version}
        </span>
        <span className="text-xs text-slate-400">nothing generated yet</span>
      </div>

      <div className="max-h-[28rem] overflow-y-auto px-4 py-3">
        <Markdown source={content.markdown} />
      </div>

      {(content.rejected ?? []).length > 0 && (
        <div className="border-t border-slate-100 bg-amber-50/60 px-4 py-2
                        text-xs text-slate-600">
          <p className="font-medium">Not applied:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {content.rejected.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3">
        <span className="mr-1 text-xs text-slate-500">Generate as</span>
        {(content.formats ?? ["powerpoint"]).map((format) => (
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
};
