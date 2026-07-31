/**
 * The files that went with a message.
 *
 * These were stored on the transcript all along — `{"files": [{"name": …}]}` —
 * and thrown away on the way to the screen: the user branch of `MessageBubble`
 * rendered `content.text`, which for an upload turn is `""`. The result was a
 * near-black rounded pill with nothing in it, which is what "the file shows as a
 * small black icon" was.
 *
 * Rendered from the *saved message*, never from the composer's local state, so
 * the record survives a reload, a chat switch and a page close.
 */

/** Per-extension marks. Cannibalised from the orphaned `UploadZone.jsx`. */
const ICONS = {
  xlsx: "📊", xls: "📊", csv: "📊",
  pptx: "📽", ppt: "📽",
  docx: "📄", doc: "📄", pdf: "📕", txt: "📄", md: "📄",
  png: "🖼", jpg: "🖼", jpeg: "🖼", gif: "🖼",
  html: "🌐", htm: "🌐",
};

export default function Attachments({ files, onRemove, compact = false }) {
  const items = files ?? [];
  if (items.length === 0) return null;

  return (
    <ul className={compact ? "flex flex-wrap gap-2" : "flex flex-col items-end gap-1.5"}>
      {items.map((file, index) => (
        <Attachment
          key={file.filename ?? file.name ?? index}
          file={file}
          onRemove={onRemove}
        />
      ))}
    </ul>
  );
}

function Attachment({ file, onRemove }) {
  // Tolerates both shapes: the server's `ChatAttachment` and the composer's
  // pre-send `{name, size}`, so a staged file and a sent one look the same.
  const name = file.filename ?? file.name ?? "file";
  const extension = (file.extension ?? name.split(".").pop() ?? "").toLowerCase();
  const failed = file.status === "failed";
  const uploading = file.status === "uploading";

  const body = (
    <>
      <span aria-hidden="true">{ICONS[extension] ?? "📎"}</span>
      <span className="max-w-[16rem] truncate font-medium">{name}</span>
      {file.size ? (
        <span className="text-slate-400">{readableSize(file.size)}</span>
      ) : null}
      {uploading && <span className="text-slate-400">uploading…</span>}
      {failed && (
        <span className="text-rag-red">{file.error || "could not be read"}</span>
      )}
    </>
  );

  return (
    <li
      className={
        "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs " +
        (failed
          ? "border-rag-red/40 bg-red-50/60 text-slate-700"
          : "border-slate-200 bg-white text-slate-700")
      }
    >
      {/* Downloadable once it is on the server; inert while staged or failed. */}
      {file.download_url && !failed ? (
        <a
          href={file.download_url}
          className="flex items-center gap-2 hover:text-slate-900"
          download
        >
          {body}
        </a>
      ) : (
        body
      )}

      {onRemove && (
        <button
          type="button"
          onClick={() => onRemove(file)}
          aria-label={`Remove ${name}`}
          className="ml-1 text-slate-400 hover:text-slate-700"
        >
          ✕
        </button>
      )}
    </li>
  );
}

function readableSize(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
