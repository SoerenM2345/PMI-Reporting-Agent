"""How much a conflict actually blocks (spec §"Conflict Handling", Phase 3).

The wizard treated an unresolved critical conflict as a hard gate: a 409, and the
whole flow stopped. A conversation cannot work that way — the user still wants an
answer, still wants a draft of the parts that *are* agreed, and should be blocked
only from the one thing that would launder a disagreement into an approved fact: a
final export.

So a conflict is graded by *impact*, not just severity:

    blocking_final_export   an unresolved critical figure — a draft may still be
                            made, but a final/approved export may not, because it
                            would present an unresolved number as settled.
    requires_user_attention worth a decision, but not export-blocking on its own.
    non_blocking            resolved, or minor.

`assess` turns the whole conflict set into a capability state the orchestrator and
UI read directly, replacing the bare 409 with `{can_respond, can_create_draft,
can_export_final, ...}`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.consistency.severity import critical_topic
from app.models.pmi import Severity
from app.project.models import ProjectKnowledge

ConflictImpact = Literal["blocking_final_export", "requires_user_attention",
                         "non_blocking"]


def impact_of(conflict) -> ConflictImpact:
    """One conflict's export impact."""
    if conflict.is_resolved:
        return "non_blocking"
    # A §9 critical topic (overall status, Day 1, go-live, budget totals, …) or any
    # high/critical-severity disagreement would present an unsettled figure as fact.
    if conflict.critical or critical_topic(conflict.entity_key) is not None:
        return "blocking_final_export"
    if conflict.severity == Severity.MEDIUM:
        return "requires_user_attention"
    return "non_blocking"


class ConflictState(BaseModel):
    """The capability envelope a turn operates within (spec's structured state)."""

    can_respond: bool = True
    can_create_draft: bool = True
    can_export_final: bool = True
    blocking_conflicts: list[dict] = Field(default_factory=list)
    attention_conflicts: list[dict] = Field(default_factory=list)
    affected_sections: list[str] = Field(default_factory=list)
    safe_sections: list[str] = Field(default_factory=list)

    def explain(self) -> str:
        """A plain-language sentence about what remains unresolved — never a card."""
        if not self.blocking_conflicts:
            return ""
        parts = []
        for c in self.blocking_conflicts[:3]:
            values = "; ".join(f"{src}: {val}" for src, val in c.get("values", {}).items())
            parts.append(f"**{c.get('entity_key')}** ({c.get('field')}) — {values}")
        lead = ("I can prepare and update the draft, but the following remains "
                "unresolved, so a final approved export is held back until you decide:")
        return lead + "\n\n" + "\n".join(f"- {p}" for p in parts)


def assess(knowledge: ProjectKnowledge) -> ConflictState:
    """Grade every conflict and derive the turn's capabilities."""
    blocking: list[dict] = []
    attention: list[dict] = []
    affected: list[str] = []

    for conflict in knowledge.data_model.conflicts:
        impact = impact_of(conflict)
        payload = {
            "conflict_id": conflict.conflict_id,
            "entity_key": conflict.entity_key,
            "field": conflict.field,
            "values": dict(conflict.values),
            "severity": conflict.severity.value,
            "impact": impact,
        }
        if impact == "blocking_final_export":
            blocking.append(payload)
            affected.append(conflict.entity_key)
        elif impact == "requires_user_attention":
            attention.append(payload)

    return ConflictState(
        can_respond=True,
        can_create_draft=True,           # partial drafts are always allowed
        can_export_final=not blocking,   # …only the *final* export is gated
        blocking_conflicts=blocking,
        attention_conflicts=attention,
        affected_sections=sorted(set(affected)),
    )
