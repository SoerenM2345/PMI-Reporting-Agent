/**
 * The natural-language request, plus the audience (spec §4 steps 2-3).
 *
 * The audience chips are shown but not preselected. §4 is explicit: if the audience
 * cannot be inferred the agent ASKS, because the audience reshapes the entire report —
 * a Steering Committee wants decisions, an IMO wants overdue tasks, and guessing wrong
 * produces a document for nobody.
 */

const PRESETS = [
  "Create a SteerCo presentation for the current PMI status.",
  "Create a weekly IMO status report.",
  "Create a Finance dashboard for integration costs and synergies.",
  "Create a risk heatmap for the integration.",
];

const AUDIENCES = [
  ["Executive", "Steering Committee — decisions and escalations"],
  ["PMO", "IMO / PMO — operational detail"],
  ["Finance", "Budget, costs and synergies"],
  ["Workstream", "A single functional workstream"],
];

export default function RequestBar({
  request,
  setRequest,
  audience,
  setAudience,
  askingAudience,
  onAnalyze,
  busy,
  canAnalyze,
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="mb-1 font-semibold text-slate-900">2 · What do you need?</h2>
      <p className="mb-3 text-sm text-slate-500">Describe the output in plain language.</p>

      <textarea
        value={request}
        onChange={(e) => setRequest(e.target.value)}
        rows={3}
        placeholder="Create a Steering Committee presentation for the current PMI status."
        disabled={busy}
        className="w-full rounded border border-slate-300 p-3 text-sm
                   focus:border-slate-500 focus:outline-none disabled:opacity-50"
      />

      <div className="mt-2 flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            disabled={busy}
            onClick={() => setRequest(preset)}
            className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-600
                       hover:border-slate-500 hover:text-slate-900 disabled:opacity-50"
          >
            {preset.replace(/^Create an? /, "").replace(/\.$/, "")}
          </button>
        ))}
      </div>

      {askingAudience && (
        <div className="mt-4 rounded border border-rag-amber/50 bg-amber-50 p-3">
          <p className="text-sm font-medium text-slate-800">
            Who is this report for?
          </p>
          <p className="mb-2 text-xs text-slate-600">
            The request did not make this clear, and the audience changes the whole
            report — so the agent is asking rather than guessing.
          </p>
        </div>
      )}

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          Audience {askingAudience && <span className="text-rag-red">— required</span>}
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {AUDIENCES.map(([value, hint]) => (
            <button
              key={value}
              type="button"
              disabled={busy}
              title={hint}
              onClick={() => setAudience(audience === value ? null : value)}
              className={`rounded border px-3 py-2 text-left text-sm transition disabled:opacity-50
                ${
                  audience === value
                    ? "border-rag-green bg-rag-green/10 font-medium text-rag-green"
                    : "border-slate-300 text-slate-600 hover:border-slate-500"
                }`}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <button
        type="button"
        onClick={onAnalyze}
        disabled={busy || !canAnalyze}
        className="mt-4 w-full rounded bg-rag-green px-4 py-2.5 font-medium text-white
                   hover:bg-rag-green/90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Analysing…" : "Analyse files"}
      </button>
    </section>
  );
}
