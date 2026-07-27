import { useState } from "react";

import Markdown from "../chat/Markdown";

/**
 * The editable report panel (spec §"Editable Report").
 *
 * A draft is free text, not a fixed template: each section renders as Markdown and
 * can be edited directly, regenerated from current project knowledge, or left
 * alone. The system never rewrites a section under the user — staleness only
 * *flags* it (the amber badge), so a hand-written paragraph is safe.
 *
 * Presentational, per the app's conventions: it holds only the local edit buffer
 * and which section is open; every write goes back through App's `run(fn)` via the
 * callbacks, and the refreshed draft comes back down as `draft`.
 */
const STATUS_STYLE = {
  draft: "bg-slate-100 text-slate-600",
  reviewed: "bg-sky-100 text-sky-700",
  approved: "bg-emerald-100 text-emerald-700",
  stale: "bg-amber-100 text-amber-700",
  potentially_stale: "bg-amber-50 text-amber-600",
};

const EXPORT_FORMATS = [
  ["powerpoint", "PowerPoint"],
  ["word", "Word"],
  ["pdf", "PDF"],
  ["excel", "Excel"],
  ["markdown", "Markdown"],
];

export default function EditableReport({
  draft,
  versions = [],
  busy = false,
  onSaveSection,
  onRegenerate,
  onExport,
  onLoadVersions,
  onRestore,
}) {
  const [editing, setEditing] = useState(null); // section_id
  const [buffer, setBuffer] = useState("");
  const [showVersions, setShowVersions] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!draft) return null;

  const startEdit = (section) => {
    setEditing(section.section_id);
    setBuffer(section.content);
  };

  const save = () => {
    onSaveSection?.(editing, buffer);
    setEditing(null);
  };

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(draft.content || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* Clipboard blocked (e.g. insecure context) — silent, non-critical. */
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white">
      {/* ---------------------------------------------------------- toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100
                      px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900">
              {draft.title}
            </h3>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium
                             ${STATUS_STYLE[draft.status] || STATUS_STYLE.draft}`}>
              {draft.status.replace("_", " ")}
            </span>
          </div>
          <p className="text-xs text-slate-400">
            version {draft.version} · based on knowledge v
            {draft.based_on_knowledge_version}
          </p>
        </div>

        <button type="button" onClick={copyAll} disabled={busy}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5
                           text-xs font-semibold text-slate-700 hover:bg-slate-50
                           disabled:opacity-40">
          {copied ? "Copied" : "Copy all"}
        </button>

        <button type="button"
                onClick={() => {
                  const next = !showVersions;
                  setShowVersions(next);
                  if (next) onLoadVersions?.();
                }}
                disabled={busy}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5
                           text-xs font-semibold text-slate-700 hover:bg-slate-50
                           disabled:opacity-40">
          History
        </button>

        <ExportMenu busy={busy} onExport={onExport} />
      </div>

      {/* ---------------------------------------------------------- versions */}
      {showVersions && (
        <div className="border-b border-slate-100 bg-slate-50 px-4 py-2">
          <ul className="space-y-1 text-xs">
            {versions.length === 0 && (
              <li className="text-slate-400">No earlier versions.</li>
            )}
            {versions.map((v) => (
              <li key={v.version} className="flex items-center justify-between">
                <span className="text-slate-600">
                  v{v.version} · {v.created_by} · {v.status.replace("_", " ")}
                </span>
                {v.version !== draft.version && (
                  <button type="button" onClick={() => onRestore?.(v.version)}
                          disabled={busy}
                          className="font-semibold text-sky-600 hover:text-sky-800
                                     disabled:opacity-40">
                    Restore
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ---------------------------------------------------------- sections */}
      <div className="divide-y divide-slate-100">
        {(draft.sections || []).map((section) => (
          <section key={section.section_id} className="px-4 py-3">
            <div className="mb-1 flex items-center gap-2">
              <h4 className="min-w-0 flex-1 truncate text-xs font-semibold
                             uppercase tracking-wide text-slate-400">
                {section.heading || section.section_id}
              </h4>
              {section.stale && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px]
                                 font-semibold text-amber-700">
                  out of date
                </span>
              )}
              {section.origin === "user" && (
                <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px]
                                 font-semibold text-sky-600">
                  your edit
                </span>
              )}
              {editing !== section.section_id && (
                <>
                  <button type="button" onClick={() => startEdit(section)}
                          disabled={busy}
                          className="text-xs font-semibold text-slate-500
                                     hover:text-slate-800 disabled:opacity-40">
                    Edit
                  </button>
                  <button type="button"
                          onClick={() => onRegenerate?.(section.section_id)}
                          disabled={busy}
                          className="text-xs font-semibold text-slate-500
                                     hover:text-slate-800 disabled:opacity-40">
                    Regenerate
                  </button>
                </>
              )}
            </div>

            {editing === section.section_id ? (
              <div>
                <textarea
                  value={buffer}
                  onChange={(e) => setBuffer(e.target.value)}
                  rows={Math.min(20, Math.max(4, buffer.split("\n").length + 1))}
                  className="w-full resize-y rounded-lg border border-slate-300
                             bg-white px-3 py-2 font-mono text-xs leading-relaxed
                             text-slate-800 outline-none focus:border-slate-400"
                />
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={save} disabled={busy}
                          className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs
                                     font-semibold text-white hover:bg-slate-700
                                     disabled:opacity-40">
                    Save
                  </button>
                  <button type="button" onClick={() => setEditing(null)}
                          disabled={busy}
                          className="rounded-lg border border-slate-300 px-3 py-1.5
                                     text-xs font-semibold text-slate-600
                                     hover:bg-slate-50 disabled:opacity-40">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <Markdown source={section.content} />
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

function ExportMenu({ busy, onExport }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} disabled={busy}
              className="rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-semibold
                         text-white hover:bg-slate-700 disabled:opacity-40">
        Export ▾
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 w-36 rounded-lg border
                        border-slate-200 bg-white py-1 shadow-lg">
          {EXPORT_FORMATS.map(([value, label]) => (
            <button key={value} type="button"
                    onClick={() => {
                      setOpen(false);
                      onExport?.(value);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-xs
                               text-slate-700 hover:bg-slate-50">
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
