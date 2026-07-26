/**
 * A small renderer for the subset of Markdown this app emits.
 *
 * Two producers, one grammar: `render_markdown` writes the report preview
 * (headings, a subtitle line, rules, pipe tables, bullets, blockquotes) and
 * `app/report/chat_format.py` writes the agent's replies (a bolded heading,
 * `•` bullets, ordered lists, key-value lines). Agent text used to be
 * interpolated as a raw string, so a reply reached the user with its `**` still
 * in it — the formatting was written and then thrown away at the last step.
 *
 * Deliberately not a library. Both producers are our own code, so the grammar
 * is closed and known; pulling in a parser to handle syntax we never emit would
 * add a dependency, a bundle, and an HTML-injection surface for text that came
 * out of somebody's uploaded spreadsheet.
 *
 * Everything is rendered as React elements, never `dangerouslySetInnerHTML`, so
 * a task title containing markup is text and stays text.
 */
export default function Markdown({ source }) {
  return <div className="text-sm leading-relaxed">{parse(source || "")}</div>;
}

function parse(source) {
  const lines = source.split("\n");
  const out = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      // A blank line is paragraph spacing, not nothing. Collapsed runs of them
      // are what made every reply read as one undifferentiated block.
      if (out.length) out.push(<div key={`s${index}`} className="h-2" />);
      while (index < lines.length && !lines[index].trim()) index += 1;
      continue;
    }

    if (line.startsWith("# ")) {
      out.push(
        <h1 key={index} className="mb-1 text-lg font-bold text-slate-900">
          {inline(line.slice(2))}
        </h1>,
      );
      index += 1;
    } else if (line.startsWith("## ")) {
      out.push(
        <h2 key={index} className="mt-4 font-semibold text-slate-900">
          {inline(line.slice(3))}
        </h2>,
      );
      index += 1;
    } else if (line.startsWith("### ")) {
      out.push(
        <h3 key={index} className="mt-3 text-sm font-semibold text-slate-900">
          {inline(line.slice(4))}
        </h3>,
      );
      index += 1;
    } else if (line.startsWith("---")) {
      out.push(<hr key={index} className="my-3 border-slate-200" />);
      index += 1;
    } else if (line.startsWith("> ")) {
      out.push(
        <p
          key={index}
          className="my-2 border-l-2 border-slate-300 pl-3 text-slate-500"
        >
          {inline(line.slice(2))}
        </p>,
      );
      index += 1;
    } else if (line.startsWith("|")) {
      const rows = [];
      while (index < lines.length && lines[index].startsWith("|")) {
        rows.push(lines[index]);
        index += 1;
      }
      out.push(<Table key={`t${index}`} rows={rows} />);
    } else if (BULLET.test(line)) {
      // `- ` from the preview, `• ` from the agent, and the indented `    · `
      // continuation lines a conflict answer uses for its per-source values.
      const items = [];
      while (index < lines.length && BULLET.test(lines[index])) {
        items.push(lines[index].replace(BULLET, ""));
        index += 1;
      }
      out.push(
        <ul key={`u${index}`} className="my-2 list-disc space-y-1 pl-5">
          {items.map((item, position) => (
            <li key={position}>{inline(item)}</li>
          ))}
        </ul>,
      );
    } else if (ORDERED.test(line)) {
      const items = [];
      while (index < lines.length && ORDERED.test(lines[index])) {
        items.push(lines[index].replace(ORDERED, ""));
        index += 1;
      }
      out.push(
        <ol key={`o${index}`} className="my-2 list-decimal space-y-1 pl-5">
          {items.map((item, position) => (
            <li key={position}>{inline(item)}</li>
          ))}
        </ol>,
      );
    } else if (/^\*[^*]+\*$/.test(line.trim())) {
      // The section label under a headline.
      out.push(
        <p key={index} className="text-xs uppercase tracking-wide text-slate-400">
          {line.trim().slice(1, -1)}
        </p>,
      );
      index += 1;
    } else {
      out.push(
        <p key={index} className="my-1.5 text-slate-700">
          {inline(line)}
        </p>,
      );
      index += 1;
    }
  }

  return out;
}

function Table({ rows }) {
  const cells = (row) =>
    row
      .replace(/^\||\|$/g, "")
      .split(/(?<!\\)\|/)          // a pipe inside a cell is escaped upstream
      .map((cell) => cell.replace(/\\\|/g, "|").trim());

  const header = cells(rows[0]);
  const body = rows.slice(2).map(cells);   // row 1 is the |---| separator

  return (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {header.map((label, index) => (
              <th
                key={index}
                className="border-b border-slate-200 bg-slate-50 px-2 py-1.5 text-left
                           font-semibold text-slate-700"
              >
                {inline(label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className="border-b border-slate-100 px-2 py-1.5 align-top text-slate-700"
                >
                  {inline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const BULLET = /^\s*(?:-|•|·)\s+/;
const ORDERED = /^\s*\d+\.\s+/;

/**
 * `**bold**` and `*italic*`. Bold is matched first so `**x**` is never read as
 * an empty italic wrapping `*x*`.
 */
function inline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={index} className="italic">
          {part.slice(1, -1)}
        </em>
      );
    }
    return <span key={index}>{part}</span>;
  });
}
