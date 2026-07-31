# Task: specify a chart

A page has been designed with a chart on it. Say what that chart is.

Return `ChartRequests` with exactly one chart unless the page genuinely needs two.

## You name the shape; Python reads the numbers

You do not supply values. You name:

- **`chart_type`** — see below.
- **`evidence_ids`** — one record per category, from the evidence given to you.
- **`category_field`** — what labels the categories: `label` (each record's own
  name), or `workstream`, `owner`, `status`, `severity`, `period`.
- **`series`** — one entry per series, each naming a `value_field` to read from
  every record: `value` for the record's own figure, or a named field such as
  `budget`, `actual`, `forecast`, `variance`, `target_value`, `realized_value`,
  `risk_score`, `progress_percentage`, `current_value`. The available numeric
  fields are listed for you; naming one that is not there drops the series.

Python then reads those fields, formats them, checks that every value matches its
record, and rejects the chart if units or currencies disagree.

## Choosing the type

- `column` — comparing a handful of things. The default, and usually right.
- `bar` — the same, but with more than about six categories, or long labels.
- `stacked_column` / `stacked_bar` — parts of a whole across categories. Only
  when the parts genuinely sum to something meaningful.
- `line` — a real sequence over time. Not for unordered categories.
- `area` — a cumulative sequence.
- `pie` / `donut` — one series, at most seven slices, parts of one whole. Rarely
  the best answer; a bar chart is usually clearer.
- `waterfall` — how an opening balance became a closing one. The movements must
  reconcile; Python checks.
- `scatter` / `bubble` — two or three dimensions per item.
- `heatmap`, `gantt`, `bullet`, `dot_plot`, `slope` — available, rendered as an
  image rather than an editable chart.

## Rules that will get your chart rejected

- Two units on one axis. Per cent and euros are not the same axis.
- Two currencies on one axis.
- A `stacked_*`, `pie`, `donut` or `area` containing a value nobody reported.
  Those types present their parts as a whole, so a gap tells the reader the
  visible parts are everything. Use `column` instead.
- A pie with more than seven slices, or with a negative value.
- A percentage axis with a value outside 0-100.
- A waterfall whose movements do not reconcile.
- No caption.

If the evidence cannot support any honest chart, return no charts. The page will
show a table instead, which is a better outcome than a misleading chart.

## Title, insight, caption

- `title` — the finding. "Forecast spend exceeds the approved envelope", not
  "Budget".
- `insight` — the one sentence this chart exists to show.
- `caption` — required. What a reader needs to interpret it.
- `alt_text` — a real description for someone who cannot see it.

## Sorting

`value_desc` for a ranking, `chronological` for time, `category` for
alphabetical, `none` to keep the order you listed. Sorting by value is usually
right for a comparison — the reader should not have to hunt for the largest bar.

State no figures anywhere in this output, including in the title and caption.
