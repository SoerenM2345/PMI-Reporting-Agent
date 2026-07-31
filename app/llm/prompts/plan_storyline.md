# Task: develop the storyline

This is the most important decision in the document. Everything after it —
titles, layout, charts, review — is execution. Get the argument right and a
plain document works; get it wrong and a beautiful one wastes the reader's time.

Produce a `StorylinePlan`.

## Find the governing message first

Read the evidence and ask: **if the reader remembers one sentence, what should
it be?**

That sentence is the `governing_message`. It is a finding, not a subject.

- Not "Integration status update" — that is a subject.
- Yes: "Integration is on track for Day 1 except in Finance, where three
  unowned tasks put payroll cutover at risk."

It must be supportable by the evidence you were given. If the evidence does not
support any single finding, say what the evidence does establish and be precise
about the uncertainty — never manufacture a conclusion to have one.

`executive_takeaway` expands it to two or three sentences: what is true, why it
matters, what happens next.

## Then structure the argument (SCQA)

- **`situation`** — what the reader already accepts. One sentence. No news here.
- **`complication`** — what changed, what went wrong, what is at risk. Do not
  bury this and do not soften it. If the evidence shows a problem, the
  complication is the problem.
- **`question`** — the question the complication forces. Usually the reader's
  real question.
- **`supporting_arguments`** — two to four claims that, taken together,
  establish the governing message. Each should be independently checkable
  against evidence. Aim for arguments that do not overlap and that together
  cover the question.

`narrative_flow` names the ordering principle you used. Choose the one that
actually fits: `decision_first` when the reader must decide something,
`by_severity` when the news is what matters, `chronological` for a retrospective
or a plan, `by_workstream` only when the reader genuinely thinks in workstreams.

## Then derive the sections

Sections fall out of the argument. They are not a checklist and there is no
standard set — no obligatory status page, no obligatory risk table, no
obligatory KPI row. Include a section because the argument needs it.

For each section:

- **`working_title`** — conclusion-oriented. "Forecast spend exceeds the
  approved envelope", not "Budget". If the evidence does not support a
  conclusion, use a precise neutral title rather than an invented one.
- **`management_question`** — what the reader is asking that this answers.
- **`intended_message`** — the single sentence this section exists to land.
- **`purpose`** — where it sits in the argument.
- **`evidence_ids`** — every record this section rests on. Required unless the
  purpose is `frame`. Use only ids present in the evidence given to you.
- **`recommended_expression`** — what *kind* of thing communicates this best:
  a `comparison` between things, a `trend` over time, a `composition` of a
  whole, a `sequence` of events, a `matrix` of two dimensions, a `table` of
  records, a `hierarchy`, or `none` for prose. You are describing the shape of
  the idea; a later stage picks the actual chart or diagram.
- **`why_this_expression`** — one clause. If you cannot justify a visual, use
  `none`; a chart that exists to look analytical is worse than a sentence.
- **`suggested_pages`** — usually 1. More only when the section genuinely
  cannot fit.
- **`depth`** — `headline_only` for something the reader needs to know exists,
  `detailed` for the section carrying the argument's weight.

## Topics you were given

If the request named topics, the plan must cover all of them. You may retitle
them, reorder them and group two closely related ones into a single section —
that is editorial judgement and it is wanted. You may not drop one. A topic with
no supporting evidence still gets a section, which states plainly that nothing
in the project covers it and what would be needed to answer it.

## Disagreements and gaps

An unresolved conflict is a finding. If two sources disagree about a figure the
argument depends on, that disagreement belongs in the document, usually near the
governing message — a reader who acts on a number the project cannot agree on
has been failed by the report, not by the data.

Evidence marked `ABSENT` is worth a sentence wherever the reader would
reasonably expect that subject to be covered.

## `evidence_not_used`

List ids you deliberately set aside. There is no penalty for setting evidence
aside and no reason to hide it; a reviewer may disagree with the judgement, and
they can only do that if they can see it.

## Reminder

State no figures anywhere in this output. Reference the evidence and let the
renderer place the values.
