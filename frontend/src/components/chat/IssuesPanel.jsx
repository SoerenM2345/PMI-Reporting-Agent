import { useState } from "react";

/**
 * Completeness gaps (§8.2), and the box to close them.
 *
 * Deliberately not a `ConflictCard`. A conflict is two files disagreeing, and
 * the question is *which do you trust* — so that card shows both claims with
 * their provenance and asks you to choose. A gap has no competing claim: the
 * value was simply never written down. Offering a "choose the source" control
 * here would imply an answer exists in the files when it does not.
 *
 * So this asks the only question that makes sense — what is the value — and
 * says plainly that it will be recorded as coming from you rather than from a
 * tracker.
 */
const LABELS = {
  due_date: "Due date",
  decision_deadline: "Deadline",
  realization_date: "Realization date",
  owner: "Owner",
  mitigation_action: "Mitigation",
};

const PLACEHOLDERS = {
  due_date: "DD-MM-YYYY",
  decision_deadline: "DD-MM-YYYY",
  realization_date: "DD-MM-YYYY",
};

export default function IssuesPanel({ content, onFill, busy }) {
  const [values, setValues] = useState({});
  const [done, setDone] = useState({});

  const issues = content.issues ?? [];
  const outstanding = issues.filter((issue) => !done[issue.issue_id]);

  const submit = async (issue) => {
    const value = (values[issue.issue_id] ?? "").trim();
    if (!value) return;
    const result = await onFill(issue.issue_id, value);
    setDone((prior) => ({
      ...prior,
      [issue.issue_id]: result?.applied
        ? { ok: true, message: result.message }
        : { ok: false, message: result?.message ?? "That value was not accepted." },
    }));
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-sm text-slate-800">{content.text}</p>
      <p className="mt-0.5 text-xs text-slate-500">
        Nothing in the files disagrees here — the value was never recorded.
        Anything you enter is marked as supplied by you, not by a source.
      </p>

      <ul className="mt-3 space-y-2">
        {issues.map((issue) => {
          const outcome = done[issue.issue_id];
          const label = LABELS[issue.field] ?? issue.field?.replace(/_/g, " ");

          return (
            <li
              key={issue.issue_id}
              className={`rounded border px-3 py-2 ${
                outcome?.ok
                  ? "border-rag-green/40 bg-rag-green/5"
                  : "border-slate-200"
              }`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate text-sm text-slate-800">
                  {issue.entity_label}
                </span>
                <span className="whitespace-nowrap text-xs text-slate-400">
                  {issue.entity_type} · {label}
                </span>
              </div>

              {outcome ? (
                <p
                  className={`mt-1 text-xs ${
                    outcome.ok ? "text-rag-green" : "text-rag-red"
                  }`}
                >
                  {outcome.ok ? "✓ " : "⚠ "}
                  {outcome.message}
                </p>
              ) : (
                <form
                  className="mt-1.5 flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submit(issue);
                  }}
                >
                  <input
                    value={values[issue.issue_id] ?? ""}
                    disabled={busy}
                    placeholder={PLACEHOLDERS[issue.field] ?? `Enter ${label}`}
                    onChange={(event) =>
                      setValues((prior) => ({
                        ...prior,
                        [issue.issue_id]: event.target.value,
                      }))
                    }
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm
                               focus:border-slate-500 focus:outline-none
                               disabled:opacity-50"
                  />
                  <button
                    type="submit"
                    disabled={busy || !(values[issue.issue_id] ?? "").trim()}
                    className="rounded bg-slate-900 px-2.5 py-1 text-xs font-medium
                               text-white hover:bg-slate-700 disabled:opacity-40"
                  >
                    Save
                  </button>
                </form>
              )}
            </li>
          );
        })}
      </ul>

      {content.total > issues.length && (
        <p className="mt-2 text-xs text-slate-500">
          Showing {issues.length} of {content.total}. The rest are in the
          data-quality report.
        </p>
      )}

      {outstanding.length === 0 && issues.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          All filled in. Ask me to re-plan so the report picks them up.
        </p>
      )}
    </div>
  );
}
