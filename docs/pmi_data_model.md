# PMI Data Model

The 14 entities of spec §6, as implemented. Field names follow the spec verbatim so
this can be diffed against §6 directly.

Code: `app/models/{enums,source,entities,quality,pmi}.py`, imported through
`app.models.pmi`.

## The rule that governs every field

> **§7 — "The agent must never silently invent missing PMI information."**

A field the source did not state is `None`. Not zero, not "Medium", not a sensible
default. Downstream, `None` renders as **"Not Reported"** — never as a blank cell and
never as `0`.

That distinction is not pedantry. A workstream shown at 0% progress has told the
Steering Committee it achieved nothing this period. A workstream shown as "Not
Reported" has told them it did not report. Those are different meetings.

## Entities

| § | Entity | Key fields |
|---|---|---|
| 6.1 | `PMIProject` | project/deal names, reporting date, signing/closing/Day-1 dates, phase, type, overall status |
| 6.2 | `Workstream` | name, lead, sponsor, status, progress, achievements, next steps, open risks/issues |
| 6.3 | `Task` | title, workstream, owner, start/due/completion dates, status, progress, `is_day_1_critical`, `is_overdue` |
| 6.4 | `Milestone` | name, planned/forecast/actual dates, `delay_days`, `is_day_1_critical`, `is_go_live` |
| 6.5 | `Risk` | category, `probability`, `impact`, `risk_score`, mitigation + owner + due date, trend |
| 6.6 | `Issue` | severity, resolution action + owner, due date, escalation |
| 6.7 | `Dependency` | providing/receiving workstream, required date, impact if delayed |
| 6.8 | `Decision` | decision body, owner, deadline, options, recommended option, impact |
| 6.9 | `BudgetItem` | budget, actual, committed, forecast, `variance`, `variance_percentage`, currency |
| 6.10 | `Synergy` | type, baseline, target, realized, forecast, `remaining_value`, realization date, confidence |
| 6.11 | `KPI` | current/target/previous value, unit, trend |
| 6.12 | `GovernanceMeeting` | type, date, participants, agenda, decisions, actions |
| 6.13 | `StatusUpdate` | reporting period, workstream, status, achievements, planned activities |
| 6.14 | `SourceReference` | file, sheet, slide, page, section, table, cell range, image region, **extraction confidence** |

## Decisions the spec left open

### Risk scales (§6.5)

The spec mandates `risk_score = probability × impact` but never defines the scales.

**We use the conventional PMI 5×5 matrix.** Both factors are integers 1–5, so the score
runs 1–25 and bands as:

| Score | Rating |
|---|---|
| 1–4 | Low |
| 5–9 | Medium |
| 10–15 | High |
| 16–25 | Critical |

**A register that gives only one rating column** (which is most of them) is read as
**impact**, with `probability = None` and therefore `risk_score = None`. We do not
invent a likelihood so that a number can be printed.

For display, a risk with only an impact is banded on impact alone (5 → Critical). The
tempting alternative — multiply by a median probability of 3 — would band a Critical
risk (5 × 3 = 15) as merely *High*, quietly demoting the worst risk in the register.
There is a regression test for exactly this.

Unscored risks appear on the heatmap's "could not be plotted" line, not in a cell. A
risk with no probability is not a low risk; it is an unassessed one, and dropping it
from the picture is how it stays unassessed.

### Dates (§7)

§7 says "Normalize dates to DD-MM-YYYY". We treat that as a **presentation** rule.

Internally, dates are `datetime.date`. Every temporal check (§8.3) is arithmetic on
real dates — a due date before a start date, a Day-1 task scheduled after Day 1, a
milestone completed in the future. Storing them as strings would make all of it
impossible. Formatting to DD-MM-YYYY happens in the generators and the UI.

### Status taxonomy (§7)

The spec's taxonomy is Not Started / In Progress / At Risk / Blocked / Completed /
Cancelled / Unknown. Two notes:

- **"red" maps to At Risk, not Blocked.** Red means "off track", which is not the same
  as "cannot proceed". Blocked is asserted only when a source says so explicitly.
- **There is no `Overdue` status.** Overdue is *derived* from the due date against the
  reporting date. That is what makes §8.2's "overdue task marked Green" check possible
  at all — if we trusted the tracker's own RAG column, we could never catch it lying.

### Workstreams are derived, not extracted (§6.2)

No PMI file contains a "workstreams" table, but every tracker tags its rows with one.
Workstream entities are built from those tags, and their progress is the mean of their
tasks' — computed in Python (§11).

Unrecognised workstream names are kept **verbatim**. A project may legitimately run a
workstream the spec never listed, and quietly relabelling "SteerCo Prep" as something
from §3's list would be exactly the kind of invention §7 forbids.

## Provenance and confidence (§6.14)

Every entity carries `source_references: list[SourceReference]` — a list, because entity
matching merges the same task seen in two files into one object holding both refs. That
is what makes cross-source conflict detection possible at all.

`extraction_confidence` runs 0.0–1.0:

| Source | Confidence |
|---|---|
| A table in a spreadsheet | 1.0 |
| Text matched by regex in a document | 1.0 |
| Read from an image by a vision model | **≤ 0.90**, multiplied down by legibility, handwriting, cropping, low resolution and blur |
| Read by local OCR | 0.40 |
| Could not be read | 0.0 — and the file is reported as a hole in the report |

The cap is deliberate (§21.14). No image reading ever reaches full confidence, so a
figure read off a screenshot always loses an automatic conflict against the spreadsheet
it was screenshotted from — which is correct.
