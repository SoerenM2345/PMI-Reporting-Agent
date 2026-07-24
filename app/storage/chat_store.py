"""Chat storage: SQLite, alongside the existing per-session JSON.

Deliberately *not* folded into `json_store`. A chat is a conversation — many
short rows, queried by recency, renamed and archived. An analysis is one large
document read whole. Putting the transcript in SQLite and leaving extraction in
JSON means a corrupt chat database costs you the conversation and nothing else:
`analysis.json` still holds the extracted model and the vision readings, which
are the expensive, unreproducible part.

That split is also what makes compaction safe. The transcript is **not** the
source of truth — `analysis.json` and `content/vN.json` are — so summarising old
turns to stay inside a context budget loses conversational nuance and never data.

One file, `storage_data/chats.db`, inside the directory the container already
bind-mounts. No new service, no migration story beyond `CREATE TABLE IF NOT
EXISTS`.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

from pydantic import BaseModel, Field

from app.config import get_settings

log = logging.getLogger("pmi.chat")

Role = Literal["user", "agent", "system"]

#: What the frontend needs in order to render a turn as something other than
#: prose — a conflict card, a file list, a preview, a download set.
Kind = Literal[
    "text", "files", "project_form", "audience_choice", "analysis",
    "conflict", "low_confidence", "issues", "preview", "downloads", "notice",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id        TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    session_id     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    archived_at    TEXT,
    provider       TEXT,
    model          TEXT,
    token_estimate INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    message_id     TEXT PRIMARY KEY,
    chat_id        TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    role           TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'text',
    content        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    superseded     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at DESC);
"""


# ------------------------------------------------------------------- models
class Chat(BaseModel):
    chat_id: str
    title: str
    session_id: str
    created_at: str
    updated_at: str
    archived_at: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    token_estimate: int = 0
    message_count: int = 0


class Message(BaseModel):
    message_id: str
    chat_id: str
    role: Role
    kind: Kind = "text"
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    token_estimate: int = 0
    #: Replaced by a compaction summary. Kept on disk — the user can still scroll
    #: back — but excluded from what is sent to a model.
    superseded: bool = False


# ---------------------------------------------------------------- plumbing
def _db_path() -> Path:
    return get_settings().storage_dir / "chats.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """A connection per operation.

    Cheap for SQLite, and it sidesteps the thread-affinity problem entirely:
    uvicorn runs handlers on a worker pool, so a module-level connection would
    need `check_same_thread=False` plus a lock, which is more machinery than a
    single-user local app needs.
    """
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def _now() -> str:
    """Microsecond resolution, deliberately.

    Sidebar order is `updated_at DESC`, and second-resolution timestamps tie
    constantly — creating a chat and sending its first message happen well
    inside one second — which makes the list reorder itself unpredictably
    between refreshes. `list_chats` still breaks remaining ties on rowid.
    """
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    """A rough characters-to-tokens ratio.

    Deliberately approximate: this drives *when to compact*, not billing, and a
    real tokenizer would tie the chat layer to one provider's client. Erring
    high is the safe direction — compacting slightly early costs a little
    history, compacting late costs the request.
    """
    return max(1, len(text or "") // 3)


# ------------------------------------------------------------------- chats
def create_chat(session_id: str, title: str = "New chat", *,
                provider: Optional[str] = None,
                model: Optional[str] = None) -> Chat:
    chat_id = uuid.uuid4().hex[:12]
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO chats (chat_id, title, session_id, created_at, "
            "updated_at, provider, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, title, session_id, now, now, provider, model),
        )
    log.info("created chat %s for session %s", chat_id, session_id)
    return Chat(chat_id=chat_id, title=title, session_id=session_id,
                created_at=now, updated_at=now, provider=provider, model=model)


def list_chats(*, include_archived: bool = False, limit: int = 100) -> list[Chat]:
    """Most recently touched first — what a sidebar wants."""
    clause = "" if include_archived else "WHERE c.archived_at IS NULL"
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT c.*, COUNT(m.message_id) AS message_count
            FROM chats c
            LEFT JOIN messages m ON m.chat_id = c.chat_id
            {clause}
            GROUP BY c.chat_id
            ORDER BY c.updated_at DESC, c.rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_chat(row) for row in rows]


def get_chat(chat_id: str) -> Optional[Chat]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT c.*, COUNT(m.message_id) AS message_count
            FROM chats c
            LEFT JOIN messages m ON m.chat_id = c.chat_id
            WHERE c.chat_id = ?
            GROUP BY c.chat_id
            """,
            (chat_id,),
        ).fetchone()
    return _chat(row) if row else None


def rename_chat(chat_id: str, title: str) -> Optional[Chat]:
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE chat_id = ?",
            (title.strip() or "Untitled chat", _now(), chat_id),
        )
    return get_chat(chat_id)


def set_model(chat_id: str, *, provider: Optional[str],
              model: Optional[str]) -> Optional[Chat]:
    """Per-chat model choice.

    Stored on the row rather than mutated into the global settings object —
    `/api/project` already does that with `source_priority` and it leaks across
    every other session in the process.
    """
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET provider = ?, model = ?, updated_at = ? "
            "WHERE chat_id = ?",
            (provider, model, _now(), chat_id),
        )
    return get_chat(chat_id)


def archive_chat(chat_id: str, archived: bool = True) -> Optional[Chat]:
    """Close a chat without destroying it — 'close' in the UI sense."""
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET archived_at = ?, updated_at = ? WHERE chat_id = ?",
            (_now() if archived else None, _now(), chat_id),
        )
    return get_chat(chat_id)


def delete_chat(chat_id: str) -> bool:
    """Drops the conversation only.

    The session's uploads, analysis and generated files stay on disk: deleting a
    chat is a tidying action, and silently discarding an expensive extraction
    would be a much larger consequence than the wording implies.
    """
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        return cursor.rowcount > 0


# ---------------------------------------------------------------- messages
def add_message(chat_id: str, role: Role, content: dict[str, Any], *,
                kind: Kind = "text") -> Message:
    message_id = uuid.uuid4().hex[:12]
    now = _now()
    tokens = estimate_tokens(json.dumps(content, default=str))

    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages (message_id, chat_id, role, kind, content, "
            "created_at, token_estimate) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, chat_id, role, kind,
             json.dumps(content, default=str), now, tokens),
        )
        connection.execute(
            "UPDATE chats SET updated_at = ?, "
            "token_estimate = token_estimate + ? WHERE chat_id = ?",
            (now, tokens, chat_id),
        )
    return Message(message_id=message_id, chat_id=chat_id, role=role, kind=kind,
                   content=content, created_at=now, token_estimate=tokens)


def list_messages(chat_id: str, *, include_superseded: bool = True) -> list[Message]:
    clause = "" if include_superseded else "AND superseded = 0"
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM messages WHERE chat_id = ? {clause} "
            f"ORDER BY created_at, rowid",
            (chat_id,),
        ).fetchall()
    return [_message(row) for row in rows]


def supersede(message_ids: list[str]) -> int:
    """Mark turns as compacted away. They stay readable in the transcript."""
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    with _connect() as connection:
        cursor = connection.execute(
            f"UPDATE messages SET superseded = 1 WHERE message_id IN ({placeholders})",
            message_ids,
        )
        return cursor.rowcount


# ------------------------------------------------------------------ mapping
def _chat(row: sqlite3.Row) -> Chat:
    return Chat(
        chat_id=row["chat_id"], title=row["title"], session_id=row["session_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        archived_at=row["archived_at"], provider=row["provider"],
        model=row["model"], token_estimate=row["token_estimate"],
        message_count=row["message_count"] if "message_count" in row.keys() else 0,
    )


def _message(row: sqlite3.Row) -> Message:
    try:
        content = json.loads(row["content"])
    except (TypeError, ValueError):
        # A row we cannot parse becomes a visible note rather than a crash or a
        # silently missing turn — the user should see that something was lost.
        log.warning("message %s has unreadable content", row["message_id"])
        content = {"text": "(this message could not be read back)"}
    return Message(
        message_id=row["message_id"], chat_id=row["chat_id"], role=row["role"],
        kind=row["kind"], content=content, created_at=row["created_at"],
        token_estimate=row["token_estimate"], superseded=bool(row["superseded"]),
    )


def live_token_estimate(chat_id: str) -> int:
    """Tokens in the turns a model would actually be sent.

    Compacted turns stay in the transcript for the user to scroll back through,
    but they are no longer part of the context, so the running total has to
    exclude them or the budget would never come back down.
    """
    with _connect() as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(token_estimate), 0) AS total FROM messages "
            "WHERE chat_id = ? AND superseded = 0",
            (chat_id,),
        ).fetchone()
    return int(row["total"])


def recount_tokens(chat_id: str) -> int:
    """Re-sync the chat's cached total after a compaction."""
    total = live_token_estimate(chat_id)
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET token_estimate = ? WHERE chat_id = ?",
            (total, chat_id),
        )
    return total
