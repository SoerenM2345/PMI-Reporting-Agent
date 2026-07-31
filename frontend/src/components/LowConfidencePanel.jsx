/**
 * Findings read out of an image or a scan (spec §5.6).
 *
 * "Low-confidence findings should be shown to the user for review." This panel is that
 * sentence. A figure the agent read off a photographed whiteboard is in the report, and
 * the user needs to know which figures those are before they take the report into a
 * room — because the agent cannot tell whether it read the number correctly, and it
 * says so rather than pretending otherwise.
 */

function bar(confidence) {
  if (confidence >= 0.6) return "bg-rag-amber";
  if (confidence >= 0.35) return "bg-orange-500";
  return "bg-rag-red";
}

export default function LowConfidencePanel({ items }) {
  return (
    <div className="rounded-lg border border-rag-amber/50 bg-amber-50/60 p-5">
      <h2 className="font-semibold text-slate-900">
        {items.length} finding{items.length === 1 ? "" : "s"} read from images — please
        verify
      </h2>
      <p className="mb-4 text-sm text-slate-600">
        These were interpreted from a screenshot, scan or photo. They are in the report,
        and they may be wrong. Check each against the source system before relying on it.
      </p>

      <ul className="space-y-2">
        {items.map((item, index) => (
          <li
            key={`${item.type}-${item.label}-${index}`}
            className="flex items-center gap-3 rounded border border-amber-200 bg-white px-3 py-2"
          >
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
              {item.type}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm text-slate-800">
              {item.label}
            </span>
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full ${bar(item.confidence)}`}
                  style={{ width: `${Math.round(item.confidence * 100)}%` }}
                />
              </div>
              <span className="w-9 text-right text-xs font-medium text-slate-600">
                {Math.round(item.confidence * 100)}%
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
