import { PreviewBlock } from "./PreviewBody";

/** The complete format-specific blueprint the user approves before generation. */
export default function FormatPreview({ preview, onEdit, onProseEdit, busy }) {
  if (!preview) return null;

  if (preview.format === "chart") {
    return (
      <div className="space-y-4">
        {(preview.charts ?? []).map((chart) => (
          <ChartDescription key={chart.block_id} chart={chart} />
        ))}
        {!preview.charts?.length && (
          <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            No chart can be generated from the available quantitative evidence.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4 text-sm">
      {preview.format === "html" && <HtmlLayout layout={preview.layout} />}
      {(preview.pages ?? []).map((page) => (
        <section
          key={page.page_id}
          className="rounded-lg border border-slate-200 bg-white p-3"
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-semibold uppercase tracking-wide text-slate-700">
              {page.label} {page.number}
            </span>
            {page.is_divider && (
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-white">
                Divider
              </span>
            )}
            <span>Layout: {page.layout || page.composition}</span>
          </div>
          {page.title && <h3 className="font-semibold text-slate-900">{page.title}</h3>}
          {page.subtitle && <p className="mt-0.5 text-slate-500">{page.subtitle}</p>}
          <div className="mt-2 space-y-2">
            {(page.content ?? []).map((block) => (
              <PreviewBlock
                key={block.block_id}
                block={block}
                onEdit={onEdit}
                onProseEdit={onProseEdit}
                busy={busy}
              />
            ))}
          </div>
          {page.speaker_notes && (
            <p className="mt-2 text-xs text-slate-500">
              Speaker notes: {page.speaker_notes}
            </p>
          )}
          {page.source_note && (
            <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-400">
              {page.source_note}
            </p>
          )}
          {(page.warnings ?? []).map((warning) => (
            <p key={warning} className="mt-1 text-xs text-amber-700">⚠ {warning}</p>
          ))}
        </section>
      ))}
    </div>
  );
}

function HtmlLayout({ layout }) {
  if (!layout) return null;
  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <h3 className="font-semibold text-slate-900">HTML layout and behavior</h3>
      <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-[7rem_1fr]">
        {Object.entries(layout).map(([name, value]) => (
          <div key={name} className="contents">
            <dt className="font-medium capitalize text-slate-600">{name.replaceAll("_", " ")}</dt>
            <dd className="text-slate-600">{Array.isArray(value) ? value.join(" · ") : value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ChartDescription({ chart }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {chart.chart_type?.replaceAll("_", " ")} chart
      </p>
      <h3 className="mt-1 font-semibold text-slate-900">{chart.title || chart.caption}</h3>
      {chart.subtitle && <p className="text-slate-500">{chart.subtitle}</p>}
      {chart.intended_message && (
        <p className="mt-2 border-l-2 border-amber-300 pl-2 text-slate-700">
          Intended message: {chart.intended_message}
        </p>
      )}
      <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-[7rem_1fr]">
        <dt className="font-medium text-slate-600">Axes</dt>
        <dd>{[chart.category_axis?.title, chart.value_axis?.title].filter(Boolean).join(" · ") || "Categories and values"}</dd>
        <dt className="font-medium text-slate-600">Legend</dt>
        <dd>{chart.legend}</dd>
        <dt className="font-medium text-slate-600">Data labels</dt>
        <dd>{chart.data_labels}</dd>
        <dt className="font-medium text-slate-600">Categories</dt>
        <dd>{(chart.categories ?? []).join(" · ")}</dd>
      </dl>
      {(chart.series ?? []).map((series) => (
        <div key={series.name} className="mt-2 overflow-x-auto">
          <p className="text-xs font-medium text-slate-700">Series: {series.name}</p>
          <table className="mt-1 w-full text-xs">
            <tbody>
              {(series.points ?? []).map((point) => (
                <tr key={`${series.name}-${point.label}`} className="border-t border-slate-100">
                  <td className="py-1 pr-3 text-slate-600">{point.label}</td>
                  <td className="py-1 text-right font-medium">{point.display || "Not Reported"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {chart.source_note && <p className="mt-2 text-xs text-slate-400">{chart.source_note}</p>}
    </section>
  );
}
