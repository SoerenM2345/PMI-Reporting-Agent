/**
 * Files the open chat into a project without leaving the conversation.
 *
 * This is deliberately a native select: drag-and-drop is convenient in the
 * sidebar, while this control remains keyboard and touch friendly.
 */
export default function ChatProjectPicker({
  chat,
  projects = [],
  busy = false,
  onChange,
}) {
  const currentProjectId = chat?.project_id || "";

  return (
    <label className="flex items-center gap-2 text-xs text-slate-500">
      <span className="sr-only">Chat project</span>
      <span aria-hidden="true">📁</span>
      <select
        aria-label="Chat project"
        value={currentProjectId}
        disabled={busy || !chat}
        onChange={(event) => onChange?.(event.target.value || null)}
        className="max-w-56 rounded-lg border border-slate-300 bg-white
                   px-2.5 py-1 text-xs text-slate-700 outline-none
                   transition hover:border-slate-500 focus:border-slate-500
                   focus:ring-2 focus:ring-slate-200 disabled:opacity-40"
      >
        <option value="">No project</option>
        {projects.map((project) => (
          <option key={project.project_id} value={project.project_id}>
            {project.icon || "📁"} {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}
