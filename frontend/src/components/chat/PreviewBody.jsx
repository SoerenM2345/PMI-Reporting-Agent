import { useState } from "react";

/**
 * The report preview, rendered from structured blocks rather than from markdown.
 *
 * Markdown is still what the Copy button hands over and what the text-only view
 * shows, but it is lossy in the one way that matters here: a cell in a markdown
 * table has no identity, so clicking it cannot become "write 12-08-2026 into
 * milestone M1's planned date". These blocks carry each cell's origin, which is
 * what makes the preview editable.
 *
 * An edit goes to the **data model**, not to the stored text. Patching the
 * preview alone would leave the deck, the workbook and the document still
 * stating the old figure — the formats disagreeing about a number the user
 * personally corrected is exactly what the shared content layer exists to
 * prevent.
 */
export default function PreviewBody({ sections, onEdit, onProseEdit, busy }) {
  if (!sections?.length) return null;

  return (
    <div className="space-y-5 text-sm">
      {sections.map((section) => (
        <section key={section.section_id}>
          <h3 className="font-semibold text-slate-900">{section.headline}</h3>
          <p className="text-xs uppercase tracking-wide text-slate-400">
            {section.label}
          </p>

          {section.blocks.map((block) => (
            <PreviewBlock
              key={block.block_id}
              block={block}
              onEdit={onEdit}
              onProseEdit={onProseEdit}
              busy={busy}
            />
          ))}

          {!section.blocks.some(hasContent) && section.empty_explanation && (
            <p className="mt-2 border-l-2 border-slate-300 pl-3 text-slate-500">
              {section.empty_explanation}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

function hasContent(block) {
  if (block.kind === "bullets") return (block.items ?? []).length > 0;
  if (block.kind === "table") return block.derived || (block.rows ?? []).length > 0;
  if (block.kind === "tiles") return (block.tiles ?? []).length > 0;
  return true;
}

export function PreviewBlock({ block, onEdit, onProseEdit, busy }) {
  if (block.kind === "bullets") {
    if (!block.items?.length) return null;
    return (
      <EditableText
        blockId={block.block_id}
        initial={block.items.map((item) => item.text).join("\n")}
        onProseEdit={onProseEdit}
        busy={busy}
      >
        {block.title && (
          <p className="font-medium text-slate-800">{block.title}</p>
        )}
        <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-700">
          {block.items.map((item, index) => (
            <li key={index} className={EMPHASIS[item.emphasis] ?? ""}>
              {item.text}
            </li>
          ))}
        </ul>
      </EditableText>
    );
  }

  if (block.kind === "prose") {
    return (
      <EditableText
        blockId={block.block_id}
        initial={block.text}
        onProseEdit={onProseEdit}
        busy={busy}
      >
        <p className="text-slate-700">{block.text}</p>
      </EditableText>
    );
  }

  if (block.kind === "tiles") {
    return (
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {(block.tiles ?? []).map((tile) => (
          <div
            key={tile.label}
            className="rounded border border-slate-200 bg-slate-50 px-3 py-2"
          >
            <p className="text-xs text-slate-500">{tile.label}</p>
            <p className={`text-lg font-semibold ${EMPHASIS[tile.emphasis] ?? "text-slate-900"}`}>
              {tile.value}
            </p>
          </div>
        ))}
      </div>
    );
  }

  if (block.kind === "chart") {
    return (
      <p className="mt-2 rounded border border-dashed border-slate-300 px-3 py-2
                    text-slate-500">
        📊 Chart: <span className="font-medium">{block.caption}</span>
      </p>
    );
  }

  if (block.kind === "table") {
    // A large listing is stored as a query, not as rows. Saying so beats
    // rendering an empty table that looks like "there is nothing here".
    if (block.derived) {
      return (
        <p className="mt-2 rounded border border-dashed border-slate-300 px-3 py-2
                      text-slate-500">
          📋 Full {block.entity} listing — included in the Excel dashboard.
        </p>
      );
    }
    if (!block.rows?.length) return null;
    return <Table block={block} onEdit={onEdit} busy={busy} />;
  }

  return null;
}

/**
 * A card's narrative text, editable as a whole rather than cell by cell.
 *
 * Read-only it renders `children` (the planned bullets or prose) with a quiet
 * "Edit text" affordance; open, it swaps in a textarea pre-filled with that
 * text so the user can rewrite or paste over it. Saving sends the whole block
 * to the data model as a user override — the deck, workbook and document all
 * pick it up, and it survives the next re-plan.
 *
 * A figure the report does not already hold is refused server-side and the
 * reason shown right here, next to the box: dates and numbers belong to the
 * table and the data model, prose does not get to invent them.
 */
function EditableText({ blockId, initial, onProseEdit, children, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(initial ?? "");
  const [rejected, setRejected] = useState(null);

  if (!onProseEdit) return <div className="mt-2">{children}</div>;

  const open = () => {
    setDraft(initial ?? "");
    setRejected(null);
    setEditing(true);
  };

  const save = async () => {
    const result = await onProseEdit({ blockId, text: draft });
    if (result && result.applied === false) {
      setRejected(result.message);
      return;
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="mt-2">
        <textarea
          autoFocus
          rows={Math.max(3, draft.split("\n").length + 1)}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setEditing(false);
            // Cmd/Ctrl+Enter saves; plain Enter is a newline between bullets.
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) save();
          }}
          className="w-full rounded border border-slate-400 px-2 py-1 text-sm
                     focus:outline-none focus:ring-1 focus:ring-amber-300"
        />
        {rejected && (
          <p className="mt-1 text-[11px] text-rag-red">{rejected}</p>
        )}
        <div className="mt-1 flex items-center gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={save}
            className="rounded bg-slate-800 px-2 py-0.5 text-xs font-medium
                       text-white hover:bg-slate-700 disabled:opacity-40"
          >
            Save
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setEditing(false)}
            className="text-xs text-slate-500 hover:text-slate-700"
          >
            Cancel
          </button>
          <span className="text-[11px] text-slate-400">
            One line per point · ⌘/Ctrl+Enter to save
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="group mt-2">
      {children}
      <button
        type="button"
        disabled={busy}
        onClick={open}
        className="mt-1 text-[11px] text-slate-400 opacity-0 transition
                   hover:text-slate-600 group-hover:opacity-100
                   disabled:opacity-0"
      >
        ✎ Edit text
      </button>
    </div>
  );
}

function Table({ block, onEdit, busy }) {
  const [editing, setEditing] = useState(null);   // "row:column"
  const [draft, setDraft] = useState("");
  const [rejected, setRejected] = useState(null); // {key, message}

  const open = (row, column, text) => {
    setEditing(`${row}:${column}`);
    setDraft(text);
    setRejected(null);
  };

  const cancel = () => {
    setEditing(null);
    setRejected(null);
  };

  const save = async (row, column) => {
    const result = await onEdit({
      blockId: block.block_id,
      row,
      column,
      value: draft,
    });
    // A rejected value is shown next to the box the user typed in — moving it
    // to a new turn further down separates the reason from what caused it.
    if (result && result.applied === false) {
      setRejected({ key: `${row}:${column}`, message: result.message });
      return;
    }
    setEditing(null);
  };

  return (
    <div className="mt-2 overflow-x-auto">
      {block.title && (
        <p className="mb-1 font-medium text-slate-800">{block.title}</p>
      )}
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {block.columns.map((column) => (
              <th
                key={column.header}
                className="border-b border-slate-200 bg-slate-50 px-2 py-1.5
                           text-left font-semibold text-slate-700"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, columnIndex) => {
                const key = `${rowIndex}:${columnIndex}`;
                const isEditing = editing === key;
                return (
                  <td
                    key={columnIndex}
                    className="border-b border-slate-100 px-2 py-1.5 align-top
                               text-slate-700"
                  >
                    {isEditing ? (
                      <>
                        <input
                          autoFocus
                          value={draft}
                          disabled={busy}
                          onChange={(event) => setDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") save(rowIndex, columnIndex);
                            if (event.key === "Escape") cancel();
                          }}
                          onBlur={() => !rejected && cancel()}
                          className="w-full rounded border border-slate-400 px-1
                                     py-0.5 text-xs focus:outline-none"
                        />
                        {rejected?.key === key && (
                          <p className="mt-1 text-[11px] text-rag-red">
                            {rejected.message}
                          </p>
                        )}
                      </>
                    ) : cell.editable ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => open(rowIndex, columnIndex, cell.text)}
                        title={`Click to edit — writes to ${cell.field}`}
                        className="w-full rounded px-1 py-0.5 text-left
                                   hover:bg-amber-50 hover:ring-1
                                   hover:ring-amber-200 disabled:opacity-40"
                      >
                        {cell.text}
                      </button>
                    ) : (
                      // Computed and composite cells are deliberately inert:
                      // a risk score and a budget variance are arithmetic this
                      // system guarantees it does itself (§11).
                      <span className="px-1">{cell.text}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {block.note && (
        <p className="mt-1 text-xs italic text-slate-500">{block.note}</p>
      )}
    </div>
  );
}

const EMPHASIS = {
  bad: "text-rag-red",
  warn: "text-rag-amber",
  good: "text-rag-green",
  muted: "text-slate-400",
};
