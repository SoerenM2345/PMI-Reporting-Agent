import ConflictCard from "./ConflictCard";
import LowConfidencePanel from "./LowConfidencePanel";

/**
 * What the agent found, and what it needs a human to decide (spec §8, §9).
 *
 * The data-quality score sits at the top on purpose. Its job is to stop someone
 * presenting a deck built from three contradictory files and a blurry screenshot as
 * though it were a clean set of accounts.
 */

function scoreColour(score) {
  if (score >= 80) return "text-rag-green";
  if (score >= 60) return "text-rag-amber";
  return "text-rag-red";
}

export default function AnalysisPanel({
  analysis,
  onResolve,
  onGenerate,
  busy,
}) {
  const {
    stats = {},
    quality_score: score,
    conflicts = [],
    unresolved_conflicts: unresolved = [],
    blocking_conflicts: blocking = [],
    validation_issues: issues = [],
    low_confidence_items: lowConfidence = [],
    errors = [],
    warnings = [],
  } = analysis;

  const counts = Object.entries(stats).filter(([, n]) => n > 0);
  const isBlocked = blocking.length > 0;

  return (
    <section className="space-y-4">
      {/* ---------------------------------------------------------- summary */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-semibold text-slate-900">3 · What the agent found</h2>
            <p className="text-sm text-slate-500">
              {counts.reduce((sum, [, n]) => sum + n, 0)} items across{" "}
              {counts.length} entity types
            </p>
          </div>
          {score !== null && score !== undefined && (
            <div className="text-right">
              <div className={`text-3xl font-bold ${scoreColour(score)}`}>
                {Math.round(score)}
                <span className="text-base font-normal text-slate-400">/100</span>
              </div>
              <div className="text-xs text-slate-500">data quality</div>
            </div>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {counts.map(([name, count]) => (
            <span
              key={name}
              className="rounded bg-slate-100 px-2.5 py-1 text-sm text-slate-700"
            >
              <strong>{count}</strong> {name.replace(/_/g, " ")}
            </span>
          ))}
        </div>

        {errors.length > 0 && (
          <div className="mt-4 rounded border border-rag-red/30 bg-red-50 p-3">
            <p className="text-sm font-medium text-rag-red">
              {errors.length} file(s) could NOT be read — their contents are missing
              from this report entirely:
            </p>
            <ul className="mt-1 text-sm text-rag-red">
              {errors.map((e) => <li key={e}>• {e}</li>)}
            </ul>
          </div>
        )}
      </div>

      {/* -------------------------------------------------------- conflicts */}
      {conflicts.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="font-semibold text-slate-900">
            {conflicts.length} cross-source conflict
            {conflicts.length === 1 ? "" : "s"}
          </h2>
          <p className="mb-4 text-sm text-slate-500">
            {isBlocked ? (
              <span className="text-rag-red">
                {blocking.length} of these change the management message and must be
                decided by a person before a report can be produced.
              </span>
            ) : (
              "All conflicts are resolved. Lower-severity ones were settled automatically by source priority."
            )}
          </p>

          <div className="space-y-3">
            {conflicts.map((conflict) => (
              <ConflictCard
                key={conflict.conflict_id}
                conflict={conflict}
                onResolve={onResolve}
                busy={busy}
              />
            ))}
          </div>
        </div>
      )}

      {/* ------------------------------------------------- low confidence */}
      {lowConfidence.length > 0 && (
        <LowConfidencePanel items={lowConfidence} />
      )}

      {/* -------------------------------------------------------- gaps */}
      {issues.length > 0 && (
        <details className="rounded-lg border border-slate-200 bg-white p-5">
          <summary className="cursor-pointer font-semibold text-slate-900">
            {issues.length} data-quality issue{issues.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-3 space-y-1.5">
            {issues.map((issue) => (
              <li key={issue.issue_id} className="text-sm">
                <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-500">
                  {issue.check_id}
                </span>
                <span
                  className={
                    ["high", "critical"].includes(issue.severity)
                      ? "text-rag-red"
                      : "text-slate-700"
                  }
                >
                  {issue.message}
                </span>
                {issue.corrected_value && (
                  <span className="ml-1 text-rag-green">
                    → corrected to {issue.corrected_value}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {warnings.length > 0 && (
        <details className="rounded-lg border border-slate-200 bg-white p-5">
          <summary className="cursor-pointer text-sm font-medium text-slate-600">
            {warnings.length} processing caveat{warnings.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-1 text-sm text-slate-500">
            {warnings.map((w, i) => <li key={i}>• {w}</li>)}
          </ul>
        </details>
      )}

      {/* -------------------------------------------------------- generate */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 font-semibold text-slate-900">4 · Generate the report</h2>

        <button
          type="button"
          onClick={() => onGenerate(false)}
          disabled={busy || isBlocked}
          className="w-full rounded bg-rag-green px-4 py-2.5 font-medium text-white
                     hover:bg-rag-green/90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Generating…" : "Generate report"}
        </button>

        {isBlocked && (
          <div className="mt-3 rounded border border-rag-red/30 bg-red-50 p-3">
            <p className="text-sm text-rag-red">
              Blocked: {blocking.length} critical conflict
              {blocking.length === 1 ? "" : "s"} unresolved. Two of your own sources
              contradict each other about something that changes the message —
              producing a deck that silently picked one would be worse than producing
              nothing.
            </p>
            <button
              type="button"
              onClick={() => onGenerate(true)}
              disabled={busy}
              className="mt-2 text-sm font-medium text-rag-red underline hover:no-underline"
            >
              Generate anyway (the outputs will say the conflicts are unresolved)
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
