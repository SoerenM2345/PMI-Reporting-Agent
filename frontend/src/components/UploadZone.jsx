import { useRef, useState } from "react";

/** Drag-and-drop for the week's files (spec §4 step 1). */

const ACCEPTED = ".xlsx,.xls,.csv,.pptx,.docx,.pdf,.html,.htm,.png,.jpg,.jpeg";

const ICONS = {
  xlsx: "📊", xls: "📊", csv: "📊",
  pptx: "📽", docx: "📄", pdf: "📕",
  html: "🌐", htm: "🌐",
  png: "🖼", jpg: "🖼", jpeg: "🖼",
};

export default function UploadZone({ files, rejected, onUpload, busy }) {
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);

  const handle = (list) => {
    if (list?.length) onUpload(Array.from(list));
  };

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="mb-1 font-semibold text-slate-900">1 · Upload PMI files</h2>
      <p className="mb-4 text-sm text-slate-500">
        Trackers, SteerCo decks, meeting minutes, PDFs, exports — and screenshots of
        dashboards or photos of whiteboards.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handle(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition
          ${dragging ? "border-rag-green bg-rag-green/5" : "border-slate-300 hover:border-slate-400"}
          ${busy ? "pointer-events-none opacity-50" : ""}`}
      >
        <p className="font-medium text-slate-700">Drop files here, or click to browse</p>
        <p className="mt-1 text-xs text-slate-400">
          Excel · CSV · PowerPoint · Word · PDF · HTML · PNG · JPG
        </p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => handle(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-4 space-y-1">
          {files.map((name) => (
            <li key={name} className="flex items-center gap-2 text-sm text-slate-700">
              <span>{ICONS[name.split(".").pop().toLowerCase()] ?? "📎"}</span>
              <span className="truncate">{name}</span>
            </li>
          ))}
        </ul>
      )}

      {rejected.length > 0 && (
        <div className="mt-3 rounded border border-rag-red/30 bg-red-50 p-3">
          {rejected.map((item) => (
            <p key={item.file} className="text-sm text-rag-red">
              <strong>{item.file}</strong> was not accepted — {item.reason}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
