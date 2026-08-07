"""What a chart, diagram or table *is* — and the request the model makes for one.

Two layers, deliberately separated, and the separation is the whole point.

A **`ChartRequest`** is what the model produces. It names a chart type, the
evidence to plot, which field of that evidence becomes each series, and how to
sort and annotate it. It contains **no values**. It cannot: there is no field
for one.

A **`ChartSpec`** is what Python produces from that request by reading the
evidence. Every `DataPoint` carries the `evidence_id` it came from, so every
mark on every chart is traceable to a cell in a file. `validator.py` then checks
that the numbers in the spec really are the numbers in the evidence before
anything is drawn.

This is why the old `Chart: Workstream Progress` stub cannot recur. A chart
either has validated data behind every point or it is not a chart, and the
caller falls back to a table or a sentence — never to a caption over empty space.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.report.content import Cell, Column, Emphasis

ChartType = Literal[
    "bar", "column", "stacked_column", "stacked_bar", "line", "area",
    "pie", "donut", "scatter", "bubble", "waterfall", "bullet",
    "heatmap", "gantt", "dot_plot", "slope",
]

#: Types python-pptx can express as a *native, editable* chart. Everything else
#: is rendered as an image and says so, because a partner who cannot re-point a
#: series at new data will rebuild the slide by hand.
NATIVE_PPTX_TYPES = frozenset({
    "bar", "column", "stacked_column", "stacked_bar", "line", "area",
    "pie", "donut", "scatter", "bubble", "waterfall",
})

#: Types whose parts must sum to a whole. A missing value cannot be stacked or
#: put in a pie: the reader would take the visible slices as the entire total.
WHOLE_OF_TYPES = frozenset({"pie", "donut", "stacked_column", "stacked_bar", "area"})

DiagramType = Literal[
    "process_flow", "timeline", "waterfall_bridge", "risk_matrix",
    "value_driver_tree", "swimlane", "milestone_track", "two_by_two",
    "dependency_map", "phase_diagram",
]

MissingPolicy = Literal["gap", "label_not_reported"]
SortOrder = Literal["none", "value_desc", "value_asc", "category", "chronological"]


# ============================================================ what the model asks
class SeriesRequest(BaseModel):
    """One series, named by *where to read it*, never by what it says."""

    name: str = Field(description="The series label a reader will see.")
    value_field: str = Field(
        default="value",
        description="Which field of each evidence record supplies this series' "
                    "number: 'value' for the record's own figure, or a named "
                    "field such as 'budget', 'actual', 'forecast', "
                    "'target_value', 'realized_value', 'risk_score'.")
    kind_override: Optional[ChartType] = Field(
        default=None,
        description="Draw this one series differently — a line over columns.")


class AnnotationRequest(BaseModel):
    """A note on the chart. Text and an anchor; no figures."""

    text: str = ""
    anchor_evidence_id: str = ""
    kind: Literal["callout", "target_line", "threshold", "band"] = "callout"


class ChartRequest(BaseModel):
    """The model's chart. Python turns it into a `ChartSpec`."""

    spec_id: str = ""
    chart_type: ChartType = "column"
    title: str = Field(default="", description="State the finding, not the topic.")
    insight: str = Field(
        default="", description="The one sentence this chart exists to show.")

    evidence_ids: list[str] = Field(
        default_factory=list,
        description="One record per category, in the order you want them, "
                    "unless `sort` says otherwise.")
    category_field: str = Field(
        default="label",
        description="What labels each category: 'label', 'workstream', "
                    "'owner', 'status', 'severity', 'period'.")
    series: list[SeriesRequest] = Field(default_factory=list)

    sort: SortOrder = "none"
    legend: Literal["none", "right", "bottom", "inline"] = "bottom"
    data_labels: Literal["none", "all", "extremes", "selected"] = "all"
    annotations: list[AnnotationRequest] = Field(default_factory=list)

    caption: str = Field(
        default="", description="Required. A chart with no caption is a chart "
                               "nobody can cite.")
    alt_text: str = ""


class DiagramNodeRequest(BaseModel):
    node_id: str = ""
    label: str = ""
    sublabel: str = ""
    parent_id: str = ""
    evidence_id: str = ""
    status: Literal["none", "good", "warn", "bad", "muted"] = "none"
    #: For a matrix: which cell. For a timeline: read from the evidence's date.
    row: Optional[int] = None
    column: Optional[int] = None


class DiagramEdgeRequest(BaseModel):
    from_id: str = ""
    to_id: str = ""
    label: str = ""
    style: Literal["solid", "dashed", "dotted"] = "solid"


class DiagramRequest(BaseModel):
    """A consulting diagram. Most need no quantitative data at all."""

    spec_id: str = ""
    diagram_type: DiagramType = "process_flow"
    title: str = ""
    insight: str = ""
    nodes: list[DiagramNodeRequest] = Field(default_factory=list)
    edges: list[DiagramEdgeRequest] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    caption: str = ""
    alt_text: str = ""
    x_axis_label: str = ""
    y_axis_label: str = ""


class ChartRequests(BaseModel):
    """Batch wrapper — the client returns one schema per call."""

    charts: list[ChartRequest] = Field(default_factory=list)


class DiagramRequests(BaseModel):
    diagrams: list[DiagramRequest] = Field(default_factory=list)


# ============================================================= what Python builds
class DataPoint(BaseModel):
    label: str = ""
    #: `None` means MISSING. It is never coerced to zero, at any layer.
    value: Optional[float] = None
    evidence_id: str = ""
    #: Formatted by Python. Renderers never re-derive a figure.
    display: str = ""
    emphasis: Emphasis = "none"
    note: str = ""

    @property
    def is_missing(self) -> bool:
        return self.value is None


class ChartSeries(BaseModel):
    name: str = ""
    points: list[DataPoint] = Field(default_factory=list)
    unit: Optional[str] = None
    currency: Optional[str] = None
    period: Optional[str] = None
    kind_override: Optional[ChartType] = None

    @property
    def values(self) -> list[Optional[float]]:
        return [p.value for p in self.points]

    @property
    def has_missing(self) -> bool:
        return any(p.is_missing for p in self.points)


class AxisSpec(BaseModel):
    title: str = ""
    unit: Optional[str] = None
    currency: Optional[str] = None
    is_percentage: bool = False
    allow_overflow: bool = False
    number_format: str = ""


class Annotation(BaseModel):
    text: str = ""
    kind: Literal["callout", "target_line", "threshold", "band"] = "callout"
    #: Resolved from evidence when the annotation needs a position.
    value: Optional[float] = None
    evidence_id: str = ""


class ChartSpec(BaseModel):
    """A chart whose every value is traceable. Validated before it is drawn."""

    spec_id: str
    chart_type: ChartType = "column"
    title: str = ""
    subtitle: str = ""
    insight: str = ""

    series: list[ChartSeries] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    category_axis: AxisSpec = Field(default_factory=AxisSpec)
    value_axis: AxisSpec = Field(default_factory=AxisSpec)
    annotations: list[Annotation] = Field(default_factory=list)

    legend: Literal["none", "right", "bottom", "inline"] = "bottom"
    data_labels: Literal["none", "all", "extremes", "selected"] = "all"
    missing_policy: MissingPolicy = "label_not_reported"

    caption: str = ""
    alt_text: str = ""
    source_note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    #: Set when the type cannot be a native pptx chart, so the renderer knows to
    #: place an image and the design critic knows it is not editable.
    render_as_image: bool = False
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_native_pptx(self) -> bool:
        return self.chart_type in NATIVE_PPTX_TYPES and not self.render_as_image

    @property
    def point_count(self) -> int:
        return sum(len(s.points) for s in self.series)

    def all_points(self) -> list[DataPoint]:
        return [p for s in self.series for p in s.points]


class DiagramNode(BaseModel):
    node_id: str = ""
    label: str = ""
    sublabel: str = ""
    parent_id: str = ""
    evidence_id: str = ""
    status: Emphasis = "none"
    row: Optional[int] = None
    column: Optional[int] = None
    #: Resolved by Python for timelines and bridges: a real date or delta.
    at: Optional[str] = None
    value: Optional[float] = None


class DiagramEdge(BaseModel):
    from_id: str = ""
    to_id: str = ""
    label: str = ""
    style: Literal["solid", "dashed", "dotted"] = "solid"


class MatrixAxes(BaseModel):
    x_label: str = ""
    y_label: str = ""
    x_ticks: list[str] = Field(default_factory=list)
    y_ticks: list[str] = Field(default_factory=list)


class DiagramSpec(BaseModel):
    spec_id: str
    diagram_type: DiagramType = "process_flow"
    title: str = ""
    insight: str = ""
    nodes: list[DiagramNode] = Field(default_factory=list)
    edges: list[DiagramEdge] = Field(default_factory=list)
    axes: Optional[MatrixAxes] = None
    caption: str = ""
    alt_text: str = ""
    source_note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExcludedRow(BaseModel):
    """A row taken out at the user's request, kept so the request can be undone.

    Excluded rather than deleted, for the reason a dropped page moves to
    `dropped_pages` instead of vanishing: the evidence still exists, and someone
    who excludes the wrong row has to be able to say so.
    """

    label: str = ""
    #: Where it sat in `rows`, so restoring puts it back rather than appending.
    position: int = 0
    cells: list[Cell] = Field(default_factory=list)
    evidence_id: str = ""
    emphasised: bool = False


class ExcludedColumn(BaseModel):
    """A column taken out at the user's request, kept so the request can be undone.

    Excluded rather than deleted so the exclusion can be reversed.
    """

    header: str = ""
    #: Where it sat in `columns`, so restoring puts it back in the right place.
    position: int = 0
    column: Optional["Column"] = None
    #: The cells from this column across all rows, for restoration.
    cells: list[Cell] = Field(default_factory=list)


class TableSpec(BaseModel):
    """Reuses `Column`/`Cell` from the existing IR — including `Cell.ref`, which
    is what makes a table cell editable and writable back to the data model."""

    spec_id: str
    title: str = ""
    columns: list[Column] = Field(default_factory=list)
    rows: list[list[Cell]] = Field(default_factory=list)
    row_evidence_ids: list[str] = Field(default_factory=list)
    #: How many rows exist, so a truncated table can say "showing 12 of 137"
    #: rather than silently presenting a sample as the whole.
    total_rows: int = 0
    row_limit: Optional[int] = None
    emphasis_rows: list[int] = Field(default_factory=list)
    #: Rows the user asked to leave out. See `ExcludedRow`.
    excluded_rows: list[ExcludedRow] = Field(default_factory=list)
    #: Columns the user asked to leave out. See `ExcludedColumn`.
    excluded_columns: list[ExcludedColumn] = Field(default_factory=list)
    caption: str = ""
    source_note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def displayed_row_count(self) -> int:
        """Rows the approved table view exposes.

        ``rows`` deliberately retains the complete evidence-backed table so a
        later revision can increase the limit without re-planning or inventing
        data.  Consumers use this count (or ``displayed_rows``) at the display
        boundary.
        """
        if self.row_limit is None:
            return len(self.rows)
        return min(max(self.row_limit, 0), len(self.rows))

    @property
    def displayed_rows(self) -> list[list[Cell]]:
        return self.rows[:self.displayed_row_count]

    @property
    def is_truncated(self) -> bool:
        total = max(self.total_rows, len(self.rows))
        return total > self.displayed_row_count

    def truncation_note(self) -> str:
        if not self.is_truncated:
            return ""
        total = max(self.total_rows, len(self.rows))
        return f"Showing {self.displayed_row_count} of {total} rows."

    def exclusion_note(self) -> str:
        """That the table is not the whole list — without reprinting what went.

        A reader of a risk table is entitled to know it was filtered; naming the
        excluded rows would republish exactly what the author asked to leave
        out, so the count is stated and the rows are not.
        """
        if not self.excluded_rows:
            return ""
        return (f"{len(self.excluded_rows)} row(s) excluded at the "
                f"author's request.")

    def column_exclusion_note(self) -> str:
        """That columns were hidden at the author's request."""
        if not self.excluded_columns:
            return ""
        return (f"{len(self.excluded_columns)} column(s) excluded at the "
                f"author's request.")

    def note(self) -> str:
        """Everything the reader needs about what this table is *not*.

        One method rather than a call per concern: the preview and all four
        renderers must say the same thing, and nothing compares them except
        `test_api_content.py::test_what_the_preview_says_is_what_the_deck_says`.
        """
        return " ".join(note for note in (self.truncation_note(),
                                          self.exclusion_note(),
                                          self.column_exclusion_note()) if note)

    @property
    def has_note(self) -> bool:
        return bool(self.note())

    # ------------------------------------------------------------ row edits
    def exclude_row(self, index: int) -> ExcludedRow:
        """Take one row out, remembering enough to put it back.

        Removed from `rows` rather than filtered at the display boundary. Two
        things depend on that: `row_evidence_ids` and `emphasis_rows` are
        index-parallel to `rows`, and every renderer — plus the cell editor in
        `deliverable/preview.py` — reads `displayed_rows` as a *prefix* of
        `rows`. Filtering instead would silently misalign both.
        """
        cells = self.rows.pop(index)
        evidence_id = (self.row_evidence_ids.pop(index)
                       if index < len(self.row_evidence_ids) else "")
        emphasised = index in self.emphasis_rows
        self.emphasis_rows = [row - 1 if row > index else row
                              for row in self.emphasis_rows if row != index]
        # `total_rows` counts what exists, so it drops too — otherwise the table
        # reports a deliberate exclusion as if it had run out of room.
        if self.total_rows > len(self.rows):
            self.total_rows -= 1
        excluded = ExcludedRow(
            label=_row_label(cells), position=index, cells=cells,
            evidence_id=evidence_id, emphasised=emphasised)
        self.excluded_rows.append(excluded)
        return excluded

    def restore_row(self, excluded: ExcludedRow) -> None:
        """Put an excluded row back where it was."""
        if excluded in self.excluded_rows:
            self.excluded_rows.remove(excluded)
        index = min(max(excluded.position, 0), len(self.rows))
        if self.total_rows >= len(self.rows):
            self.total_rows += 1
        self.rows.insert(index, excluded.cells)
        if index <= len(self.row_evidence_ids):
            self.row_evidence_ids.insert(index, excluded.evidence_id)
        self.emphasis_rows = [row + 1 if row >= index else row
                              for row in self.emphasis_rows]
        if excluded.emphasised:
            self.emphasis_rows.append(index)

    # ---------------------------------------------------------- column edits
    def exclude_column(self, index: int) -> ExcludedColumn:
        """Take one column out, remembering enough to put it back.

        Removes the column from `columns` and pops the cell at that index from
        every row (and from any previously-excluded rows, to keep them aligned).
        """
        if index < 0 or index >= len(self.columns):
            raise IndexError(f"column index {index} out of range [0, {len(self.columns)})")

        column = self.columns.pop(index)
        column_cells = []
        for row_idx, row in enumerate(self.rows):
            if index < len(row):
                column_cells.append(row.pop(index))
        # Also remove from any previously-excluded rows to keep them aligned.
        for excluded_row in self.excluded_rows:
            if index < len(excluded_row.cells):
                excluded_row.cells.pop(index)

        excluded = ExcludedColumn(
            header=column.header, position=index, column=column,
            cells=column_cells)
        self.excluded_columns.append(excluded)
        return excluded

    def restore_column(self, excluded: ExcludedColumn) -> None:
        """Put an excluded column back where it was."""
        if excluded in self.excluded_columns:
            self.excluded_columns.remove(excluded)
        if excluded.column is None:
            return
        index = min(max(excluded.position, 0), len(self.columns))
        self.columns.insert(index, excluded.column)
        # Restore cells to each row, in order.
        for row_idx, row in enumerate(self.rows):
            cell = (excluded.cells[row_idx] if row_idx < len(excluded.cells)
                    else Cell())
            row.insert(index, cell)
        # Also restore to any previously-excluded rows.
        for excluded_row in self.excluded_rows:
            cell = (excluded.cells[len(self.rows) + excluded_row.position]
                    if len(self.rows) + excluded_row.position < len(excluded.cells)
                    else Cell())
            excluded_row.cells.insert(index, cell)


def _row_label(cells: list[Cell]) -> str:
    """What to call a row: its first piece of text."""
    return next((cell.text.strip() for cell in cells if cell.text.strip()), "")
