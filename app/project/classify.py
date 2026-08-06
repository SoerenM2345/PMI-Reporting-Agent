"""What a chat message *is*, before it is allowed to touch knowledge (correction #2).

A conversational workspace takes everything through one text box: questions,
formatting requests, and genuine corrections all arrive the same way. Only some of
them are facts, and letting a formatting request ("make it shorter") or a question
("what's the completion rate?") edit the knowledge base would corrupt it. So every
message is classified first, and only `new_fact` / `correction` / `decision` /
`assumption` may reach knowledge — `instruction` and `no_knowledge_change` are audit
only.

Two more axes travel with the contribution and gate *how* a fact lands:

* **authority** (correction #5) — hedged language ("maybe", "I think", "around")
  makes a value `proposed`/`uncertain`, which is kept *alongside* the current value
  and flagged, never auto-superseding it. "what if" / "suppose" makes it
  `scenario_only`.
* **scope** (correction #4) — a scenario message is `scenario`-scoped and must not
  modify canonical project knowledge.

Classification uses the LLM when one is configured and a keyword model otherwise —
the same discipline as `agent/conversation.py`, and what keeps this testable with no
API key. The keyword path is deliberately conservative: when unsure it returns
`no_knowledge_change`, because wrongly ignoring a fact is recoverable (the user
restates it) while wrongly editing knowledge is not.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.project.models import (
    KnowledgeScope,
    MessageContribution,
    UserInputAuthority,
)

log = logging.getLogger("pmi.project.classify")


class Classification(BaseModel):
    contribution: MessageContribution
    authority: UserInputAuthority = "confirmed"
    scope: KnowledgeScope = "project_canonical"

    @property
    def is_knowledge(self) -> bool:
        """Does this message carry something that may update the knowledge base?"""
        return self.contribution in ("new_fact", "correction", "decision",
                                     "assumption")


# --- keyword signals -----------------------------------------------------------
_INSTRUCTION = re.compile(
    r"\b(report|deck|slides?|presentation|generate|create a|make a|export|"
    r"download|rewrite|reword|shorten|shorter|longer|expand|summar|"
    r"bullet|format|tone|more positive|less|focus on|drop the|remove the|"
    r"add a section|regenerate)\b", re.I)

_SCENARIO = re.compile(
    r"\b(what if|what-if|if we|suppose|hypothetical|scenario|imagine|"
    r"let'?s say|assuming (?:we|that)|in the case where)\b", re.I)

_UNCERTAIN = re.compile(
    r"\b(maybe|might|may be|possibly|perhaps|not sure|unsure|i think|i believe|"
    r"roughly|around|approximately|about|tbc|to be confirmed|probably|"
    r"could be|i guess)\b", re.I)

_PROPOSED = re.compile(
    r"\b(propos|suggest|recommend|we could|let'?s plan for|pencil in)\b", re.I)

_DECISION = re.compile(
    r"\b(we decided|decision[:]|it'?s decided|we agreed|agreed to|approved|"
    r"sign(?:ed)? off|go with|we'?ll go with|steerco decided)\b", re.I)

_ASSUMPTION = re.compile(
    r"\b(assume|assuming|assumption|for planning purposes|take it that|"
    r"working assumption)\b", re.I)

# Language that marks a value as replacing an existing one rather than adding a
# new one — the difference between `correction` and `new_fact`.
_CORRECTION = re.compile(
    r"\b(actually|now|moved to|changed to|should (?:be|now be|read)|"
    r"is now|are now|outdated|out of date|out-of-date|wrong|incorrect|"
    r"instead of|no longer|correction|update[d]? to|has moved|revised to|"
    r"supersed)\b", re.I)


def classify_message(text: str, *, provider: Optional[str] = None,
                     model: Optional[str] = None) -> Classification:
    """Classify one chat message. LLM when configured, keyword model otherwise."""
    local = classify_by_keyword(text)
    # Questions, explicit instructions, decisions and parseable values are
    # unambiguous.  Paying for a network classifier before every project turn
    # made latency at least two serial model calls even when a regex had already
    # settled the route.  Reserve the model for genuinely ambiguous statements.
    if local.contribution != "no_knowledge_change" or _is_question(text):
        return local
    llm = _classify_llm(text, provider=provider, model=model)
    if llm is not None:
        return llm
    return local


def classify_by_keyword(text: str) -> Classification:
    from app.agent import nl_updates

    raw = (text or "").strip()
    if not raw:
        return Classification(contribution="no_knowledge_change")
    lowered = raw.lower()

    authority = _authority(lowered)
    scenario = bool(_SCENARIO.search(lowered)) or authority == "scenario_only"
    scope: KnowledgeScope = "scenario" if scenario else "project_canonical"

    # A value-shaped sentence ("ERP go-live is 15-09-2026") is the strongest signal
    # of a fact/correction, and it is what the downstream applier can actually act
    # on. Checked before the instruction/question keywords so "the owner should be
    # Anna" is not mistaken for a formatting instruction because it contains "be".
    update = nl_updates.parse(raw)

    if _DECISION.search(lowered):
        return Classification(contribution="decision", authority=authority,
                              scope=scope)
    if _ASSUMPTION.search(lowered):
        return Classification(contribution="assumption", authority=authority,
                              scope=scope)

    if update is not None:
        contribution: MessageContribution = (
            "correction" if _CORRECTION.search(lowered) else "new_fact")
        return Classification(contribution=contribution, authority=authority,
                              scope=scope)

    # No parseable value. A question or a formatting request carries no fact.
    if _is_question(raw) or _INSTRUCTION.search(lowered):
        return Classification(
            contribution="instruction" if _INSTRUCTION.search(lowered)
            else "no_knowledge_change")

    return Classification(contribution="no_knowledge_change")


def _authority(lowered: str) -> UserInputAuthority:
    if _SCENARIO.search(lowered):
        return "scenario_only"
    if _UNCERTAIN.search(lowered):
        return "uncertain"
    if _PROPOSED.search(lowered):
        return "proposed"
    return "confirmed"


def _is_question(text: str) -> bool:
    if text.strip().endswith("?"):
        return True
    return bool(re.match(r"^(what|why|how|when|who|which|where|is|are|can|could|"
                         r"do|does|did|should|will|would)\b", text.strip(), re.I))


# --- LLM path ------------------------------------------------------------------
class _LLMClassification(BaseModel):
    contribution: MessageContribution = Field(
        description="What the message contributes.")
    authority: UserInputAuthority = Field(
        default="confirmed",
        description="How certain the user is. Hedged language is uncertain; "
                    "'what if'/'suppose' is scenario_only.")
    scope: KnowledgeScope = Field(
        default="project_canonical",
        description="scenario for hypotheticals; otherwise project_canonical.")


_SYSTEM = """You classify one message in a Post-Merger Integration reporting chat.

Decide what it contributes to project knowledge:
- new_fact: states a fact not previously given
- correction: replaces/updates a value that already exists
- decision: records a decision the user/committee made
- assumption: a working assumption, explicitly not a confirmed fact
- instruction: a request about the report/wording/format, not a fact
- no_knowledge_change: a question or small talk

Also judge authority (confirmed / proposed / uncertain / scenario_only) from the
user's certainty, and scope (project_canonical or scenario). A hypothetical
("what if the date slips?") is scenario_only and scenario-scoped. Never treat a
formatting request or a question as a fact."""


def _classify_llm(text: str, *, provider: Optional[str],
                  model: Optional[str]) -> Optional[Classification]:
    from app.config import get_settings
    from app.llm import LLMError, get_client

    client = get_client(provider)
    if client.name == "none":
        return None
    try:
        # Classification is a tiny routing task.  Running it on a selected
        # reasoning model (especially Opus) added the slowest model round-trip
        # before the actual answer.  Keep the chat's provider, but use that
        # provider's fast role and a tight response budget.
        fast = get_settings().models_for(provider, model).fast
        result = client.structured(
            system=_SYSTEM, user=text, output_model=_LLMClassification,
            model=fast, max_tokens=192,
        )
    except LLMError as exc:
        log.warning("message classification failed (%s); using keywords", exc)
        return None
    return Classification(contribution=result.contribution,
                          authority=result.authority, scope=result.scope)
