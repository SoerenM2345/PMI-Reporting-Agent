import { downloadUrl } from "../api";

/** The deliverables (spec §17: "Downloadable outputs"). */

const KIND = {
  pptx: { icon: "📽", label: "Presentation" },
  xlsx: { icon: "📊", label: "Dashboard" },
  png: { icon: "📈", label: "Chart" },
  md: { icon: "📋", label: "Report" },
};

export default function Downloads({ sessionId, outputs, summary, unresolved }) {
  return (
    <section className="rounded-lg border border-rag-green/40 bg-white p-5">
      <h2 className="mb-1 font-semibold text-slate-900">Your report is ready</h2>

      {unresolved?.length > 0 && (
        <div className="my-3 rounded border border-rag-red/30 bg-red-50 p-3 text-sm text-rag-red">
          Generated with {unresolved.length} unresolved conflict
          {unresolved.length === 1 ? "" : "s"}. The figures shown are one source's view,
          not an agreed position — the data-quality report says so.
        </div>
      )}

      {summary?.length > 0 && (
        <ul className="my-3 space-y-1.5">
          {summary.map((line, index) => (
            <li key={index} className="text-sm text-slate-700">• {line}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {outputs.map((name) => {
          const extension = name.split(".").pop().toLowerCase();
          const kind = KIND[extension] ?? { icon: "📎", label: "File" };

          return (
            <a
              key={name}
              href={downloadUrl(sessionId, name)}
              download
              className="flex items-center gap-3 rounded border border-slate-200 px-3 py-2.5
                         hover:border-rag-green hover:bg-rag-green/5"
            >
              <span className="text-xl">{kind.icon}</span>
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-800">{kind.label}</div>
                <div className="truncate text-xs text-slate-500">{name}</div>
              </div>
            </a>
          );
        })}
      </div>

      <p className="mt-4 border-t border-slate-100 pt-3 text-xs italic text-slate-500">
        Prototype output — requires Senior Manager review before distribution to
        stakeholders.
      </p>
    </section>
  );
}
