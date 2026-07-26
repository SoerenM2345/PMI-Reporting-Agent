"""One shape for every reply the agent writes.

Chat answers used to be assembled ad hoc at each call site, so the same kind of
finding came back as a paragraph in one handler and a bullet list in another, and
some replies ended with an unrelated suggestion while others ended with nothing.
A user reading a stream of answers cannot tell "this is the whole answer" from
"this trailed off" unless the shape is constant.

The shape is always the same three parts:

    **A bolded heading** — what this answer is about
    • short bullets, one finding each
    A closing line saying what the user can do about it — and nothing else.

This is Markdown by design: `MessageBubble.jsx` renders agent text through
`Markdown.jsx`, so `**bold**` reaches the user as bold rather than as literal
asterisks. Keep to what that renderer supports — headings, bold, italic, bullets
and ordered lists. There is no HTML here and no parser on the other end.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: What a list truncates to before it stops being readable in a chat bubble.
MAX_ITEMS = 12


def reply(
    heading: str,
    body: Optional[Iterable[str]] = None,
    *,
    action: str = "",
) -> str:
    """A complete answer: heading, body lines, one closing action line."""
    lines = [f"**{heading}**"]
    body_lines = [line for line in (body or []) if line]
    if body_lines:
        lines.append("")
        lines.extend(body_lines)
    if action:
        lines.append("")
        lines.append(action)
    return "\n".join(lines)


def bullets(items: Iterable[str], *, limit: int = MAX_ITEMS) -> list[str]:
    """Bullet lines, truncated with an honest count of what was left out.

    "…and 40 more" is not a garnish: a list silently cut at twelve tells the
    reader they have seen everything, which is a claim about the data.
    """
    items = [str(i) for i in items if str(i).strip()]
    shown = [f"• {item}" for item in items[:limit]]
    if len(items) > limit:
        shown.append(f"…and {len(items) - limit} more.")
    return shown


def key_values(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """`• **Label** — value` lines, for a breakdown rather than a list."""
    return [f"• **{label}** — {value}" for label, value in pairs if label]


def numbered(items: Iterable[str], *, limit: int = MAX_ITEMS) -> list[str]:
    """An ordered list, for steps whose order is the point."""
    items = [str(i) for i in items if str(i).strip()]
    shown = [f"{n}. {item}" for n, item in enumerate(items[:limit], start=1)]
    if len(items) > limit:
        shown.append(f"…and {len(items) - limit} more.")
    return shown


def count(n: int, singular: str, plural: str = "") -> str:
    """`1 risk` / `3 risks`, so replies never read "1 risk(s)"."""
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"
