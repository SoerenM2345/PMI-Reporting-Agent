# Task: specify a diagram

A page has been designed with a diagram on it. Say what that diagram is.

Most of what an integration deck needs to communicate is not quantitative — a
phase plan, a governance model, a dependency chain, a risk grid — and a diagram
says it better than a table.

Return `DiagramRequests` with one diagram.

## Types

- `process_flow` — sequential steps or stages. Drawn as chevrons.
- `phase_diagram` — integration phases, pre-Day 1 through steady state.
- `timeline` / `milestone_track` — dated events. Python places each marker by
  its real date, so the spacing shows the actual cadence. Needs at least two
  dated records.
- `risk_matrix` / `two_by_two` — two scored dimensions. Python reads each item's
  probability and impact from the evidence; set `x_axis_label` and
  `y_axis_label`.
- `value_driver_tree` — a value broken into its drivers. Exactly one root; every
  other node names its `parent_id`.
- `swimlane` — activities by owner or workstream, using `parent_id` as the lane.
- `dependency_map` — what depends on what, with `edges`.
- `waterfall_bridge` — an opening balance to a closing one.

## Nodes and edges

For each node: a `node_id` you invent, a `label`, an optional `sublabel`, and the
`evidence_id` it represents where one applies. Set `status` to `good`, `warn`,
`bad` or `muted` to colour it; leave it `none` and Python will colour it from the
evidence's own severity and status.

You may omit `nodes` entirely for a timeline or a matrix and just give
`evidence_ids` — Python will derive the nodes, their dates and their coordinates
from the evidence, which is more reliable than you restating them.

For each edge: `from_id`, `to_id`, an optional `label`, and a `style` of `solid`,
`dashed` or `dotted`.

## Keep labels short

These are drawn as shapes on a slide, and a node's box is a fraction of an inch
tall. Two or three words per label, detail in the `sublabel`. A label that does
not fit is flagged by the overflow check and has to be rewritten.

## What will get the diagram rejected

- No nodes, or a node with no label.
- A node naming a parent or an edge naming an endpoint that is not in the
  diagram.
- A timeline with fewer than two dated records.
- A matrix where nothing has both coordinates.
- A value-driver tree with no single root.
- No caption.

If the evidence does not support a diagram, return none. The page will show a
table or prose instead.

State no figures in this output.
