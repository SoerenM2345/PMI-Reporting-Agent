# Reporting Logic

How the agent decides what to check, what to ask, and what to say.

## The checks (§8)

39 checks in four families. 32 are registered in `app/agent/consistency/`; the other 7
run inside `app/agent/calculations.py`, because they *correct* a value as well as
reporting it.

### §8.1 Cross-source (12) — sources disagree

| ID | Finds |
|---|---|
| PMI-001 | Overall project status conflict (Excel green, deck amber) |
| PMI-002 | Overall progress conflict (**the spec's 82 vs 75**) |
| PMI-003 | Workstream / task status conflict |
| PMI-004 | Task progress conflict |
| PMI-005 | Task owner conflict |
| PMI-006 | Milestone date conflict (ERP go-live 15-09 vs 30-09) |
| PMI-007 | Risk rating conflict |
| PMI-008 | Synergy value conflict |
| PMI-009 | Budget figure conflict |
| PMI-010 | Day 1 readiness conflict |
| PMI-011 | Dependency status conflict (HR says delivered, IT says outstanding) |
| PMI-012 | Reporting period conflict (one file is June, another is labelled July) |

### §8.2 Mathematical (10) — the arithmetic does not hold

MATH-001 progress > 100% · MATH-002 negative realized synergy · MATH-003 variance ≠
budget − forecast · MATH-004 completed with no completion date · MATH-005 completed
milestone with a future actual date · MATH-006 overdue task marked green · MATH-007
risk score ≠ probability × impact · MATH-008 realized synergy exceeds target ·
MATH-009 workstream progress inconsistent with its own tasks · MATH-010 total budget ≠
the sum of its lines.

Where the right answer is computable, **the computed value wins** and the disagreement
is reported. A tracker that gets its own arithmetic wrong should not have that error
laundered into a board pack.

### §8.3 Temporal (7) — the dates cannot be true

TIME-001 due before start · TIME-002 completed before started · TIME-003 open item
forecast to finish in the past · **TIME-004 Day-1 activity scheduled after Day 1**
(always critical) · TIME-005 TSA exit before the TSA begins · TIME-006 completed with a
future actual date · TIME-007 risk closed before its mitigation was done.

### §8.4 Completeness (10) — what is missing

COMP-001 critical task with no owner · **COMP-002 critical risk with no mitigation**
(always critical) · COMP-003 mitigation with no owner · COMP-004 decision with no
deadline · COMP-005 workstream that did not report · COMP-006 budget line with no
forecast · COMP-007 synergy with no realization date · COMP-008 dependency with no
owner · COMP-009 item with no source reference · COMP-010 project header incomplete.

This family exists *because* of §7's rule against inventing missing data. Having refused
to invent it, the agent owes the user a clear statement of what is absent. A critical
risk with no mitigation owner is not a formatting problem — it is the most useful thing
an IMO could learn from the report, and it belongs on the slide.

## Conflict resolution (§9)

| Mode | Behaviour |
|---|---|
| **A** — ask | Every conflict goes to the user. |
| **B** — priority | Source priority decides everything. |
| **C** — hybrid | Auto-resolve low and medium; ask on high and critical. **The default.** |

Source priority (§9), user-overridable per project:

```
Excel / CSV  1   ← the system of record
Word / PDF   2
PowerPoint   3
HTML         4
Image        5   ← least trusted (§21.14)
```

### Severity: topic first, magnitude second

The spec's worked example is 82% vs 75% — a **9% relative delta**. A severity rule based
on the size of the disagreement would call that "medium", auto-resolve it, and never
tell the user. But §20 step 9 says the system *must* ask.

So severity escalates on **topic** first, encoding §9's list of critical conflicts:

> overall integration status · Day 1 readiness · major go-live dates · budget totals ·
> synergy realization · critical risks · Steering Committee decisions · TSA exit dates ·
> regulatory milestones

Magnitude is the second axis: ≥20% relative delta bumps a level, ≥50% goes straight to
critical. This catches a material disagreement about a topic §9 never listed.

### The user may state the truth

§9 Mode A asks *"Which value should be used?"* — not *"which file do you prefer?"* When
both sources are stale, picking the least-wrong one is not a resolution. So the conflict
card always offers a free-text field alongside the source options, and a user-supplied
value is written back into the model like any other resolution.

### The 409

`POST /api/generate` returns **409 Conflict** while a critical conflict is unresolved.

This is the gate that makes Mode C mean anything. Two of the user's own sources
contradict each other about something that changes the management message; a deck that
silently picked one would be the single most damaging thing this system could produce.
`force: true` overrides it — and the outputs then say, on the face of them, that they
were generated with unresolved conflicts.

## Management messages (§12.5)

> "Use clear management-message titles." — §12.5, and the Minto Pyramid Principle.

A slide titled **"Risks"** tells a reader nothing. A slide titled **"2 critical risks
have no mitigation action — an owner is needed now"** tells them what to do. Titles are
written from the data, in `pptx_report.py::_status_message` and its siblings:

| Situation | Title |
|---|---|
| Unresolved conflicts | "Integration status cannot be stated with confidence — 1 source conflict remains unresolved" |
| Unmitigated critical risks | "2 critical risks have NO mitigation action — an owner is needed now" |
| Overdue work | "5 tasks are overdue and need re-planning" |
| Clean | "Integration is on track at 82% overall progress" |

## Audiences (§12.1–12.4)

These are four different documents, not one document with a different cover.

| Audience | Leads with | Contains |
|---|---|---|
| **Executive** (SteerCo) | Is it on track? What changed? What needs you? | Status tiles, workstream progress, milestones, critical risks, financials, decisions, next steps |
| **PMO / IMO** | Operational detail | Scorecard, task status, overdue work, dependencies, **missing updates**, actions |
| **Finance** | Money | Budget vs actual vs forecast, variance, synergy target vs realized, financial risks |
| **Workstream** | One stream | Its objectives, blockers, dependencies, and what it needs from other streams |

The PMO deck's **"Missing updates and data-quality gaps"** slide is the one no tracker
produces and the most valuable one in the pack: *who has not reported*. A workstream that
says nothing looks identical to one that is fine.

## The two reports that ship with every run

Not on request — always (§18.18, §18.19).

- **Conflict report** — every disagreement, what each source said and exactly where,
  which value was used, and on what authority.
- **Data-quality report** — the score, what could not be read, what was read off a
  picture and at what confidence, every validation issue, and every processing caveat
  (including "no LLM was configured, so the summary is template prose").

The deck states one number per fact, because a deck must. These two files are where the
arithmetic behind that number is shown. Without them the deck is an assertion; with
them it is a defensible position.
