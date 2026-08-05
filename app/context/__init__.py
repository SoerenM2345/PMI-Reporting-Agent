"""Everything a deliverable is generated from, assembled once.

`builder.build_for_project()` and `builder.build_for_session()` both return a
`GenerationContext` carrying the project's identity and knowledge, the user's
verbatim request and its explicit demands, the evidence index, and the template
and brand system to render onto.

One object, passed to every stage. The alternative — each stage fetching what it
needs — is how the request and the project's own context came to reach the
chat and nothing else.
"""
from __future__ import annotations

from app.context.builder import (
    build_for_project,
    build_for_session,
    check_completeness,
    requested_audience,
    requested_sections,
    requested_visuals,
    resolve_project_name,
    user_constraints,
)
from app.context.schemas import (
    ChatExcerpt,
    CompanyNames,
    ContextGap,
    GenerationContext,
    KnowledgeDigest,
    SourceUseConstraint,
    TransactionContext,
    UserConstraint,
)

__all__ = [
    "ChatExcerpt",
    "CompanyNames",
    "ContextGap",
    "GenerationContext",
    "KnowledgeDigest",
    "SourceUseConstraint",
    "TransactionContext",
    "UserConstraint",
    "build_for_project",
    "build_for_session",
    "check_completeness",
    "requested_audience",
    "requested_sections",
    "requested_visuals",
    "resolve_project_name",
    "user_constraints",
]
