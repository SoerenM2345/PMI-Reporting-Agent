/**
 * A small, non-intrusive status indicator (spec §"Project Updates").
 *
 * "New file processed · Knowledge updated to version 8" — a quiet line, never a
 * big card, because a routine update should not demand attention. A `stale` draft
 * badge is the one thing that does, so it gets a warning colour.
 */
export default function StatusPill({ knowledgeVersion, staleCount = 0, note }) {
  if (knowledgeVersion == null && !note) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
      {note && <span>{note}</span>}
      {knowledgeVersion != null && (
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-100
                         px-2 py-0.5 font-medium text-slate-600">
          Project knowledge · v{knowledgeVersion}
        </span>
      )}
      {staleCount > 0 && (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100
                         px-2 py-0.5 font-medium text-amber-700">
          {staleCount} draft{staleCount === 1 ? "" : "s"} may be out of date
        </span>
      )}
    </div>
  );
}
