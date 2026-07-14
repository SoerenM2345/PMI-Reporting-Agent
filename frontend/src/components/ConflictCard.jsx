import { useState } from "react";

/**
 * One cross-source disagreement, and the interface for resolving it (spec §9 Mode A).
 *
 * The spec's Mode A example asks "Which value should be used?" — not "which file do
 * you prefer". That distinction is the whole design of this card: when both sources
 * are stale, picking the least-wrong one is not a resolution. So alongside the source
 * options there is always a field for the user to state the correct figure outright.
 *
 * Every claim shows WHERE it came from — sheet, cell, slide, page, image region — and
 * how confident the extraction was. "Two files disagree" is not actionable. "Workplan
 * cell A7 says 82%, slide 4 of the SteerCo deck says 75%" is.
 */

const SEVERITY = {
  critical: { label: "Critical", cls: "bg-rag-red text-white" },
  high: { label: "High", cls: "bg-orange-600 text-white" },
  medium: { label: "Medium", cls: "bg-rag-amber text-slate-900" },
  low: { label: "Low", cls: "bg-slate-200 text-slate-700" },
};

export default function ConflictCard({ conflict, onResolve, busy }) {
  const [custom, setCustom] = useState("");

  const severity = SEVERITY[conflict.severity] ?? SEVERITY.medium;
  const resolved = conflict.resolved_value !== null;

  return (
    <div
      className={`rounded-lg border p-4 ${
        resolved ? "border-slate-200 bg-white" : "border-rag-red/40 bg-red-50/40"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-xs font-semibold ${severity.cls}`}>
              {severity.label}
            </span>
            <span className="text-xs text-slate-500">{conflict.check_id}</span>
          </div>
          <h3 className="mt-1 font-semibold text-slate-900">
            {conflict.entity_key}
            <span className="ml-2 font-normal text-slate-500">
              ({conflict.field.replace(/_/g, " ")})
            </span>
          </h3>
        </div>

        {resolved && (
          <span className="whitespace-nowrap rounded bg-rag-green/10 px-2 py-1 text-xs font-medium text-rag-green">
            → {conflict.resolved_value}
          </span>
        )}
      </div>

      <p className="mt-2 text-sm text-slate-600">{conflict.message}</p>

      {/* What each source actually says, and exactly where it says it. */}
      <div className="mt-3 space-y-2">
        {conflict.evidence.map((item) => {
          const ref = item.source_reference;
          const lowConfidence = ref.extraction_confidence < 0.6;

          return (
            <button
              key={ref.file_name}
              type="button"
              disabled={busy}
              onClick={() => onResolve(conflict.conflict_id, ref.file_name)}
              className={`flex w-full items-center justify-between rounded border px-3 py-2 text-left transition
                ${
                  conflict.resolved_from === ref.file_name
                    ? "border-rag-green bg-rag-green/10"
                    : "border-slate-200 bg-white hover:border-slate-400"
                }
                disabled:cursor-not-allowed disabled:opacity-50`}
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-800">
                  {ref.file_name}
                </div>
                <div className="truncate text-xs text-slate-500">
                  {ref.location ?? "location not recorded"}
                  {lowConfidence && (
                    <span className="ml-2 font-medium text-rag-red">
                      ⚠ read at {Math.round(ref.extraction_confidence * 100)}% confidence
                    </span>
                  )}
                </div>
              </div>
              <span className="ml-3 whitespace-nowrap text-lg font-bold text-slate-900">
                {item.value}
              </span>
            </button>
          );
        })}
      </div>

      {/* §9 Mode A: the user may know that BOTH files are wrong. */}
      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (custom.trim()) {
            onResolve(conflict.conflict_id, { value: custom.trim() });
            setCustom("");
          }
        }}
      >
        <input
          value={custom}
          onChange={(event) => setCustom(event.target.value)}
          placeholder="…or enter the correct value"
          disabled={busy}
          className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm
                     focus:border-slate-500 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !custom.trim()}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white
                     hover:bg-slate-700 disabled:opacity-40"
        >
          Use this
        </button>
      </form>

      {conflict.resolution_note && (
        <p className="mt-2 text-xs italic text-slate-500">{conflict.resolution_note}</p>
      )}
    </div>
  );
}
