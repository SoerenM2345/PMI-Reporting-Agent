"""Turn "adjust slide 3" into a set of ops, then apply them.

The model's job here is *interpretation*, not authorship of facts: it reads the
instruction and the report's table of contents, and returns operations. It never
sees the position to write a figure into, because `ReviseOp` has no such field
(`ops.py`), and any prose it does write is checked against the report's own
numbers before being accepted (`guard.py`).

With no API key this falls through to `revise_fallback.interpret`, which handles
the common instructions deterministically. That is the same try-LLM →
validate → fall back → *record a warning* pattern the rest of the pipeline uses:
the feature degrades, it does not vanish, and the run says so.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.llm import LLMError, get_client
from app.report import revise_fallback
from app.report.content import ReportContent
from app.report.ops import ContentRevision, RevisionResult, apply

log = logging.getLogger("pmi.report.revise")

SYSTEM = """You edit the structure of a Post-Merger Integration report.

You are given the report's sections and a user instruction. Return operations
that carry out the instruction.

Rules:
- You may reorder, remove, restore, retitle and reword. You may add commentary.
- You may NEVER state a figure that is not already in the report. Every number
  you write is checked against the report's own data and the edit is rejected if
  it does not match. If you are unsure of a number, do not write one.
- Do not remove the data-quality section; it is required.
- Prefer the smallest set of operations that satisfies the request.
- If the instruction is unclear, return no operations and say why in `rationale`.
"""


def revise(
    content: ReportContent,
    instruction: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[RevisionResult, list[str]]:
    """`(result, warnings)`. Never raises for an unusable instruction."""
    warnings: list[str] = []
    revision = _interpret(content, instruction, provider, model, warnings)

    if not revision.ops:
        return (
            RevisionResult(content=None, applied=[], rejected=[]),
            warnings + [revision.rationale or "the instruction was not understood"],
        )

    result = apply(content, revision, instruction=instruction)
    for refusal in result.rejected:
        log.info("revision op refused: %s", refusal.reason)
    return result, warnings


def _interpret(
    content: ReportContent,
    instruction: str,
    provider: Optional[str],
    model: Optional[str],
    warnings: list[str],
) -> ContentRevision:
    client = get_client(provider)
    if client.name == "none":
        return revise_fallback.interpret(instruction, content)

    try:
        return client.structured(
            system=SYSTEM,
            user=_prompt(content, instruction),
            output_model=ContentRevision,
            model=model,
        )
    except LLMError as exc:
        # §21.17: the caveat reaches the user rather than being swallowed.
        warnings.append(
            f"The revision was interpreted without a language model ({exc}); "
            f"only simple instructions are understood in this mode."
        )
        log.warning("revision LLM call failed (%s); using keyword fallback", exc)
        return revise_fallback.interpret(instruction, content)


def _prompt(content: ReportContent, instruction: str) -> str:
    """Show the model the table of contents — never the figures.

    It does not need the numbers to decide what to reorder or remove, and not
    sending them removes the temptation to quote one back.
    """
    lines = ["Report sections, in order:"]
    for section in content.narrative():
        lines.append(f"- {section.section_id}: “{section.label}” — {section.headline}")

    hidden = [s for s in content.sections if s.narrative_order is None]
    if hidden:
        lines += ["", "Removed but restorable:"]
        lines += [f"- {s.section_id}: “{s.label}”" for s in hidden]

    lines += ["", f"Instruction: {instruction}"]
    return "\n".join(lines)
