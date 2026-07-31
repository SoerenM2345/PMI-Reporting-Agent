/**
 * Files this turn produced.
 *
 * Beside the answer, never instead of it: the assistant says what it built and
 * what it put in it, and the download sits underneath. The old `downloads` card
 * was the whole reply, so a generated deck arrived with no explanation of what
 * was in it.
 */

const ICONS = {
  pptx: "📽", docx: "📄", pdf: "📕", xlsx: "📊", html: "🌐", png: "🖼",
  md: "📄", other: "📎",
};

const LABELS = {
  pptx: "PowerPoint", docx: "Word", pdf: "PDF", xlsx: "Excel", html: "HTML",
  png: "Image", md: "Markdown",
};

export default function Artifacts({ artifacts }) {
  const items = artifacts ?? [];
  if (items.length === 0) return null;

  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((file) => (
        <li key={file.filename}>
          <Artifact file={file} />
        </li>
      ))}
    </ul>
  );
}

function Artifact({ file }) {
  const label = LABELS[file.type] ?? file.type;
  const ready = file.status === "ready";

  const inner = (
    <>
      <span aria-hidden="true" className="text-base">
        {ICONS[file.type] ?? ICONS.other}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-slate-800">
          {file.title || file.filename}
        </span>
        <span className="block text-xs text-slate-500">
          {label}
          {/* An interrupted or failed run must not offer a file as though it
              were finished — a half-written deck opening is worse than none. */}
          {file.status === "stopped" && " · stopped before it finished"}
          {file.status === "failed" && " · could not be produced"}
          {file.status === "generating" && " · still building"}
        </span>
      </span>
      {ready && <span className="text-xs text-slate-400">Download</span>}
    </>
  );

  const shell =
    "flex items-center gap-3 rounded-lg border px-3 py-2 text-sm " +
    (ready
      ? "border-slate-200 bg-white hover:border-slate-400"
      : "border-slate-200 bg-slate-50 text-slate-500");

  return ready ? (
    <a href={file.download_url} download className={shell}>
      {inner}
    </a>
  ) : (
    <div className={shell}>{inner}</div>
  );
}
