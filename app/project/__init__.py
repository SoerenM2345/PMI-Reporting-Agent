"""Project-centric storage and the incremental knowledge engine.

The app is being refactored from a session-centric, re-read-everything pipeline
into a project-centric workspace where every input is a *source* that updates a
**versioned project knowledge base**. This package owns that store and the engine
that rebuilds knowledge incrementally.

The design principle is **incremental extraction, holistic re-derivation**:
extraction (especially vision, §5.6) is the only expensive, non-deterministic
step, so it is the only thing cached per file (keyed by content hash). The cheap,
deterministic tail — standardize → calculate → match → check → resolve → quality —
is re-run over the *union* of active files' cached records, so cross-source
matching and conflict detection stay correct after every change.

Built in checkpoints:
    1A  storage core + repositories + deterministic rebuild   (this checkpoint)
    1B  source/audit events, message classification, scoped facts
    1C  stale-draft dependency tracking, migration, concurrency/acceptance

Business logic reaches storage only through the repository protocols in
`repositories.py`, so JSON/JSONL can be swapped for SQLite/Postgres later without
touching the agent logic.
"""
