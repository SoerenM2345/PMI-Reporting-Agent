# Task: title the document and every page

You are seeing all the pages at once. That is deliberate: written one at a time,
titles repeat their opening — six slides beginning "Delivery remains…" — and no
single page can see it happening.

Return `DocumentTitles`.

## Page titles state findings

A title is the one thing a reader takes from the page if they read nothing else.

Prefer:

> Forecast integration spend exceeds the approved budget
> Synergy realisation is progressing, but three initiatives lack delivery dates
> ERP migration and rebranding costs require Committee intervention

Over:

> Budget Analysis
> Synergy Status
> Cost Overview

Where the evidence does not support a conclusion, use a precise neutral title —
"Data-protection risks: current register and owners" — rather than inventing a
finding to sound decisive. A title the page cannot support is worse than a dull
one.

## Constraints

- Keep titles under about 100 characters. They are set in a single-line box on
  the slide; longer ones are flagged as overflow and have to be rewritten.
- State no figures. Not in the title, not in the subtitle. Python places values.
- Do not number the pages or write "continued".
- Cover, divider and closing pages take short titles, not findings.
- Vary the openings. If two titles would start the same way, rewrite one.

## Document title and subtitle

`document_title` names the document as its reader would refer to it — the
transaction or project name and what this is. Use the company or deal names
where you have them; never a generic placeholder.

`document_subtitle` carries the reader, the period, or the transaction in one
line.

Give every page a `PageTitle` with its `page_id`, even where you are keeping the
working title unchanged.
