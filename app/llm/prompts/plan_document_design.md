# Task: design the pages

The argument is settled. Decide how it is laid out.

Produce a `DocumentDesign`: a list of `PageIntent`, in reading order.

## Compose for the message, not from a template

There is no standard page. A page can be one strong chart with a one-line
conclusion; an executive message with three supporting points; a timeline; a
process diagram; a comparison; a risk matrix; a decision page; a full page of
narrative; a table with the exceptions highlighted; or a single sentence in
large type.

Choose per page. A document where every page has the same shape has told the
reader nothing about which page matters.

**Vary the rhythm deliberately.** A dense analytical page lands harder after a
sparse one. If you find yourself giving four consecutive pages the same
composition, you are filling a template, not designing.

## Compositions

- `single` — one column. Narrative, a full-width table, a single diagram.
- `two_column` — two ideas side by side, or evidence beside interpretation.
- `three_column` / `four_column` — parallel items of equal weight. Four is
  rarely right; if the items are not genuinely parallel, use a table.
- `hero_chart` — one chart dominating the page, with a conclusion.
- `chart_plus_commentary` — chart on one side, what it means on the other.
- `matrix` — two dimensions crossed. Risk matrices, prioritisation grids.
- `table_full` — a table that needs the page.
- `kpi_banner` — a row of figures across the top. Use this when the numbers
  *are* the message, not as decoration on every page.
- `quote` — one sentence in large type, nothing else. Reserve it for the
  governing message or a genuine turning point. It is powerful once and limp
  three times.
- `full_bleed` — an image filling the page.

## Purposes

- `cover` — first page. Title and subject.
- `divider` — a section break. Use only when the document is long enough that
  the reader needs one.
- `content` — everything that carries the argument.
- `appendix` — supporting detail the reader may not need.
- `closing` — a final ask or next steps, when the document has one.

Do not add a cover, a divider and a closing out of habit. A four-page CFO brief
needs none of them.

## Elements

Each page lists its `elements`. For every one:

- **`role`** — `headline`, `kicker`, `body`, `bullets`, `table`, `chart`,
  `diagram`, `kpi_row`, `callout`, `quote`, `image`, `source_note`.
- **`intent`** — what this element must communicate, in a sentence. For a chart
  or diagram this is what a later stage will build the specification from, so be
  concrete about what is being compared or shown.
- **`evidence_ids`** — the records behind it. A `chart`, `table` or `kpi_row`
  with no evidence ids cannot be built and will be dropped.
- **`prominence`** — exactly one `primary` element per page. That is the thing
  the reader's eye should land on. `supporting` explains it; `aside` is a
  caveat or a source note.

`visual_hierarchy` lists element roles in the order the reader should meet them.

## Titles

`message_title` is the page's headline and it should state the finding:
"Three initiatives lack confirmed delivery dates", not "Synergy Status". Where
the evidence does not support a conclusion, be precisely neutral instead of
vaguely conclusive.

`supporting_message` is one line under it, or empty. Do not pad it.

## Length

If the request named a page count, hit it. Cut the least load-bearing sections
rather than compressing every page into unreadability.

## What Python does after you

You name a composition; Python binds it to a real layout in the template and
computes every coordinate. If the template cannot serve a composition, the page
degrades to the nearest one that exists and says so. So choose the composition
that fits the message — not the one you think the template has.

You reference evidence; Python resolves the values, formats them, and places
them. State no figure yourself, including in `message_title`.
