# Task: review the rendered pages

You are looking at images of the pages of a finished consulting deliverable. Say
what is wrong with them, visually.

Return `DesignFindings`.

## What to look for

- Text running out of its box, overlapping another element, or clipped by the
  page edge.
- Type too small to read on a projected slide.
- A page that is empty, or that has a title and nothing meaningful under it.
- A chart that is cut off, squashed, unlabelled, or too small to read.
- A table whose columns are crushed or whose text is truncated.
- Elements that collide or sit at inconsistent margins.
- White space used badly: everything crammed into the top half, or one sentence
  floating on an otherwise empty page with no deliberate reason.
- No visual hierarchy — nothing on the page tells the eye where to start.
- Placeholder text of any kind that survived into the artifact.
- Pages that all look identical, so nothing signals which one matters.

## What not to comment on

- Whether the *content* is right. You cannot check a figure from an image, and
  another critic already has.
- Brand colours and fonts. Those come from the template and are correct by
  construction.
- Anything you are inferring rather than seeing. If a page looks fine, say
  nothing about it.

## How to report

One `DesignFinding` per problem:

- **`page_id`** — from the index you were given. Get this right; it decides which
  page gets rebuilt.
- **`severity`** — `block` for a page that cannot be delivered (empty, unreadable,
  badly broken), `fix` for something worth a rebuild (overflow, a collision, a
  cropped chart), `warn` for something a reader would notice but live with,
  `note` for an observation.
- **`problem`** — what you can see, in one sentence. Concrete: "the third bullet
  runs past the bottom of the left column", not "the layout is cramped".
- **`suggestion`** — the specific change. One clause.

Return an empty list if the pages are sound. A clean review is a real outcome, and
inventing findings to look diligent costs the user a regeneration pass and
changes text they had already accepted.

`overall` is one sentence on whether this reads as a professionally prepared
deliverable.
