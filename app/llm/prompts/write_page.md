# Task: write one page

Write the text for this page. Return `PageCopy`.

## What each part is for

- **`message_title`** — the page's headline. State the finding. If the evidence
  does not support a conclusion, be precisely neutral rather than vaguely
  conclusive.
- **`supporting_message`** — one line under it, or empty. Do not pad.
- **`body`** — the prose. Where the page has a body element.
- **`bullets`** — where the page has a bullets element. Full clauses, not
  fragments; at most seven; each one a point, not a label.
- **`callout`** — where the page has a callout: the thing that must not be
  missed. One or two sentences.
- **`speaker_notes`** — what the presenter should say that is not on the page.
  Genuinely useful here: the caveat, the likely question, the answer.

## How to write a substantive section

Three things, in this order, without labelling them:

1. What happened.
2. Why it matters to this reader.
3. What they should do about it.

Not a list of the source values. The evidence is on the page beside your text,
usually as a chart or a table; restating it in prose wastes the reader's only
scarce resource.

Write like this:

> The finance trackers show integration spending inside the approved budget on an
> actual-cost basis. The current forecast does not hold, driven mainly by ERP
> migration and rebranding. The Committee should confirm whether the additional
> expenditure is absorbed centrally or offset by reducing scope.

Not like this:

> Budget: as per tracker. Actual: as per tracker. Forecast: higher. Variance:
> negative. Recommendation: review.

## Figures

State none. Every number a reader sees is placed by Python from the evidence you
cite. Refer to a figure in words — "exceeds the approved budget", "roughly a
third of the target" is *not* acceptable either if it implies a proportion the
evidence does not state — and let the chart or table carry the value.

Text containing a figure that is not in the evidence is rejected and replaced
with a plainer deterministic version, so inventing one costs you the sentence.

## When the evidence is thin

Say what is known, what it suggests, what cannot be concluded, and what the
reader should clarify. Be specific about the gap: "no source records mitigation
owners for the two highest-scoring risks" is useful; "some data is missing" is
not.

Never write filler. Not "no summary was produced", not "data not available", not
"to be confirmed" standing alone.

## Contested and transcribed figures

If the evidence for this page is marked `CONTESTED`, say so in the text — a
reader who acts on a number the project cannot agree on has been failed by the
report. If it is marked with a low confidence or as read from an image, the
caption already discloses that; do not repeat it, but do not assert the figure as
settled either.
