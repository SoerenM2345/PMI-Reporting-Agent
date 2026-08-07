# Task: interpret the request

Read what the user asked for and fill in an `OutputBrief`.

You are not planning the document yet. You are establishing what kind of
document it is, who reads it, what they must be able to do afterwards, and what
it has to cover.

## What to get right

**`scope_topics` is a contract.** If the user named sections, every one of them
belongs here, in their words and in their order. Do not merge two into one, do
not drop the one you think is redundant, and do not add topics they did not ask
for. Later stages are allowed to retitle and regroup; this list is what
coverage is checked against, so anything missing here can never be checked.

A topic named in a sentence is a named topic. "A KPI dashboard tracking Day 1
readiness, completion % and overdue tasks" names three, and they are the whole
contract: it is a request for those three things, not for a status pack that
happens to mention them. Carry them across even though the user typed no
bulleted list, and add nothing beside them.

If the user named no topics at all — "put together the usual SteerCo pack",
"how are we doing?" — leave `scope_topics` empty rather than inventing a table
of contents. A later stage will decide the shape from the evidence.

**The reader is not the document.** "For SteerCo" tells you `audience_label`
and nothing about scope. A request addressed to a Steering Committee is not
thereby a request for the eight-section Steering Committee pack, and where the
user asked for something narrower — a dashboard, a one-pager, three named
topics — giving them the pack is ignoring them. `document_kind` follows the
form the user asked for; `custom` is the honest answer for a dashboard.

**`audience_label` is the reader in the user's own words.** "the CFO", "the
Steering Committee", "Anna's workstream leads". Do not normalise these to a
category — a CFO one-pager and a SteerCo pack are different documents, and
collapsing them is how every report ends up looking the same.

**`reader_goal` is a verb.** "Decide whether to hold the Day 1 date." "Approve
the additional ERP spend." "Brief the board without being surprised in the
Q&A." If you cannot tell, say what the reader most plausibly needs to do, in one
sentence.

**`decisions_sought`** — only decisions the reader is actually being asked to
take. An empty list is correct for a pure status update.

**`document_kind`** — pick the closest. `custom` is available and is the right
answer when nothing fits; it is not a failure.

**`target_page_count`** — only when the user stated or clearly implied a limit
("a one-pager", "no more than 8 slides", "keep it short" implies nothing
specific, so leave it null).

**`open_questions_for_user`** — what you would ask before writing, if you could.
This is genuinely useful; the interface shows it. Two or three at most, and only
things that would change the document.

## What not to do

Do not restate the request back. Do not pad `scope_topics` to look thorough. Do
not state any figure anywhere in this output — not in the title proposal, not in
the reader goal.
