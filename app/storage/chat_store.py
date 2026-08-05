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
CREATE TABLE IF NOT EXISTS projects (
    project_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    icon           TEXT NOT NULL DEFAULT '📁',
    knowledge      TEXT NOT NULL DEFAULT '',
    pinned         INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id        TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    session_id     TEXT NOT NULL,
    project_id     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    archived_at    TEXT,
    provider       TEXT,
    model          TEXT,
    pinned         INTEGER NOT NULL DEFAULT 0,
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


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring a pre-projects database up to the current schema.

    `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a `chats.db`
    created before projects existed keeps its old column set. Adding `project_id`
    with a guarded `ALTER` is the whole migration story — the `projects` table
    itself is created fresh by `_SCHEMA`, and untagged chats simply carry a NULL
    `project_id`, which is exactly "outside a project".

    The `project_id` index is created here rather than in `_SCHEMA` because the
    column it references may not exist until the `ALTER` above has run.
    """
    chat_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(chats)")
    }
    if "project_id" not in chat_columns:
        connection.execute("ALTER TABLE chats ADD COLUMN project_id TEXT")
    if "pinned" not in chat_columns:
        connection.execute(
            "ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
        )
    project_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(projects)")
    }
    if "pinned" not in project_columns:
        connection.execute(
            "ALTER TABLE projects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chats_project ON chats(project_id)"
    )


# ------------------------------------------------------------------- models
class Project(BaseModel):
    project_id: str
    name: str
    icon: str = "📁"
    #: Free text the user pins to the project — background, glossary, standing
    #: instructions. Persisted here so it survives across the project's chats;
    #: wiring it into a turn's context is a separate, later concern.
    knowledge: str = ""
    pinned: bool = False
    created_at: str
    updated_at: str
    chat_count: int = 0


class Chat(BaseModel):
    chat_id: str
    title: str
    session_id: str
    #: NULL means the chat lives outside any project — the default.
    project_id: Optional[str] = None
    created_at: str
    updated_at: str
    archived_at: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    pinned: bool = False
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
        _migrate(connection)
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
                model: Optional[str] = None,
                project_id: Optional[str] = None) -> Chat:
    chat_id = uuid.uuid4().hex[:12]
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO chats (chat_id, title, session_id, project_id, "
            "created_at, updated_at, provider, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, title, session_id, project_id, now, now, provider, model),
        )
    log.info("created chat %s for session %s (project %s)",
             chat_id, session_id, project_id or "-")
    return Chat(chat_id=chat_id, title=title, session_id=session_id,
                project_id=project_id, created_at=now, updated_at=now,
                provider=provider, model=model)


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
            ORDER BY c.pinned DESC, c.updated_at DESC, c.rowid DESC
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


def get_chat_for_session(session_id: str) -> Optional[Chat]:
    """The most recently active chat backed by this analysis session."""
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT c.*, COUNT(m.message_id) AS message_count
            FROM chats c
            LEFT JOIN messages m ON m.chat_id = c.chat_id
            WHERE c.session_id = ?
            GROUP BY c.chat_id
            ORDER BY c.updated_at DESC, c.rowid DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return _chat(row) if row else None


def rename_chat(chat_id: str, title: str) -> Optional[Chat]:
    """Rename in place — deliberately leaves `updated_at` untouched.

    The sidebar is ordered `updated_at DESC`, so bumping the timestamp here would
    yank a renamed chat to the top of the list, which is not what "rename" means.
    A rename changes the chat's label, not its recency; only new activity
    (`add_message`, `set_model`, `archive_chat`) should reorder the sidebar.
    """
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET title = ? WHERE chat_id = ?",
            (title.strip() or "Untitled chat", chat_id),
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


def pin_chat(chat_id: str, pinned: bool) -> Optional[Chat]:
    """Pin or unpin without changing conversational recency."""
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET pinned = ? WHERE chat_id = ?",
            (int(pinned), chat_id),
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


# ---------------------------------------------------------------- projects
def create_project(name: str, *, icon: str = "📁",
                   knowledge: str = "") -> Project:
    project_id = uuid.uuid4().hex[:12]
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO projects (project_id, name, icon, knowledge, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name.strip() or "Untitled project",
             icon or "📁", knowledge or "", now, now),
        )
    log.info("created project %s", project_id)
    return Project(project_id=project_id, name=name.strip() or "Untitled project",
                   icon=icon or "📁", knowledge=knowledge or "",
                   created_at=now, updated_at=now)


def list_projects() -> list[Project]:
    """Every project, each with a count of the chats filed under it.

    Ordered by name so the sidebar list is stable — projects are a filing
    structure, not a recency feed like the chat list.
    """
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT p.*, COUNT(c.chat_id) AS chat_count
            FROM projects p
            LEFT JOIN chats c
                ON c.project_id = p.project_id AND c.archived_at IS NULL
            GROUP BY p.project_id
            ORDER BY p.pinned DESC, p.name COLLATE NOCASE, p.rowid
            """,
        ).fetchall()
    return [_project(row) for row in rows]


def get_project(project_id: str) -> Optional[Project]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT p.*, COUNT(c.chat_id) AS chat_count
            FROM projects p
            LEFT JOIN chats c
                ON c.project_id = p.project_id AND c.archived_at IS NULL
            WHERE p.project_id = ?
            GROUP BY p.project_id
            """,
            (project_id,),
        ).fetchone()
    return _project(row) if row else None


def update_project(project_id: str, *, name: Optional[str] = None,
                   icon: Optional[str] = None,
                   knowledge: Optional[str] = None,
                   pinned: Optional[bool] = None) -> Optional[Project]:
    """Rename, re-icon, or re-knowledge a project — any subset in one call.

    Only the fields the caller actually passes are written; `None` means "leave
    it", which is what lets the icon picker and the rename box touch the same row
    without clobbering each other's value.
    """
    sets: list[str] = []
    values: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        values.append(name.strip() or "Untitled project")
    if icon is not None:
        sets.append("icon = ?")
        values.append(icon or "📁")
    if knowledge is not None:
        sets.append("knowledge = ?")
        values.append(knowledge)
    if pinned is not None:
        sets.append("pinned = ?")
        values.append(int(pinned))
    if not sets:
        return get_project(project_id)

    sets.append("updated_at = ?")
    values.append(_now())
    values.append(project_id)
    with _connect() as connection:
        connection.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE project_id = ?",
            values,
        )
    return get_project(project_id)


def delete_project(project_id: str) -> bool:
    """Delete the project, keeping its chats.

    Its chats are pushed back out to the top level (`project_id = NULL`) rather
    than cascade-deleted: a project is a folder, and deleting a folder in this
    app must never take a week's conversations with it. Same reasoning as
    `delete_chat` sparing the analysis.
    """
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET project_id = NULL WHERE project_id = ?",
            (project_id,),
        )
        cursor = connection.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,)
        )
        return cursor.rowcount > 0


def set_chat_project(chat_id: str, project_id: Optional[str]) -> Optional[Chat]:
    """Move a chat into a project, or out of one when `project_id` is None.

    Leaves `updated_at` alone for the same reason `rename_chat` does — filing a
    chat is not activity in it, and should not jump it to the top of the list.
    """
    with _connect() as connection:
        connection.execute(
            "UPDATE chats SET project_id = ? WHERE chat_id = ?",
            (project_id, chat_id),
        )
    return get_chat(chat_id)


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


def list_project_messages(project_id: str, *, include_superseded: bool = False
                          ) -> list[Message]:
    """Conversation context across every live chat filed in a project."""
    superseded = "" if include_superseded else "AND m.superseded = 0"
    with _connect() as connection:
        rows = connection.execute(
            f"""SELECT m.* FROM messages m
                JOIN chats c ON c.chat_id = m.chat_id
                WHERE c.project_id = ? AND c.archived_at IS NULL {superseded}
                ORDER BY m.created_at, m.rowid""",
            (project_id,),
        ).fetchall()
    return [_message(row) for row in rows]


def search(query: str, *, limit: int = 40) -> list[dict[str, Any]]:
    """Search project names/knowledge and every live chat transcript.

    Content is decoded before matching so results are human text rather than
    JSON fragments. The data set is local and intentionally bounded by the
    response limit; avoiding an FTS shadow table keeps old databases migration
    free and ensures nested message payloads remain searchable.
    """
    needle = query.strip().casefold()
    if not needle:
        return []

    with _connect() as connection:
        project_rows = connection.execute(
            "SELECT * FROM projects ORDER BY pinned DESC, name COLLATE NOCASE"
        ).fetchall()
        chat_rows = connection.execute(
            """
            SELECT c.*, p.name AS project_name
            FROM chats c
            LEFT JOIN projects p ON p.project_id = c.project_id
            WHERE c.archived_at IS NULL
            ORDER BY c.pinned DESC, c.updated_at DESC, c.rowid DESC
            """
        ).fetchall()
        message_rows = connection.execute(
            """
            SELECT m.chat_id, m.role, m.content, m.created_at
            FROM messages m
            JOIN chats c ON c.chat_id = m.chat_id
            WHERE c.archived_at IS NULL
            ORDER BY m.created_at DESC, m.rowid DESC
            """
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in project_rows:
        matching = row["name"] if needle in row["name"].casefold() else row["knowledge"]
        if needle in (matching or "").casefold():
            results.append({
                "type": "project",
                "project_id": row["project_id"],
                "title": row["name"],
                "icon": row["icon"],
                "snippet": _snippet(matching, needle),
            })

    messages_by_chat: dict[str, list[sqlite3.Row]] = {}
    for row in message_rows:
        messages_by_chat.setdefault(row["chat_id"], []).append(row)

    for row in chat_rows:
        snippet = ""
        role: Optional[str] = None
        if needle in row["title"].casefold():
            snippet = row["title"]
        else:
            for message_row in messages_by_chat.get(row["chat_id"], []):
                try:
                    content = json.loads(message_row["content"])
                except (TypeError, ValueError):
                    continue
                text = " ".join(_content_strings(content))
                if needle in text.casefold():
                    snippet = _snippet(text, needle)
                    role = message_row["role"]
                    break
        if snippet:
            results.append({
                "type": "chat",
                "chat_id": row["chat_id"],
                "project_id": row["project_id"],
                "project_name": row["project_name"],
                "title": row["title"],
                "snippet": snippet,
                "role": role,
            })
        if len(results) >= limit:
            break
    return results[:limit]


def _content_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _content_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _content_strings(child)]
    return []


def _snippet(text: str, needle: str, *, width: int = 150) -> str:
    clean = " ".join((text or "").split())
    position = clean.casefold().find(needle)
    if position < 0 or len(clean) <= width:
        return clean
    start = max(0, position - width // 3)
    end = min(len(clean), start + width)
    return ("…" if start else "") + clean[start:end] + ("…" if end < len(clean) else "")


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
def _project(row: sqlite3.Row) -> Project:
    keys = row.keys()
    return Project(
        project_id=row["project_id"], name=row["name"], icon=row["icon"],
        knowledge=row["knowledge"], created_at=row["created_at"],
        updated_at=row["updated_at"],
        pinned=bool(row["pinned"]) if "pinned" in keys else False,
        chat_count=row["chat_count"] if "chat_count" in keys else 0,
    )


def _chat(row: sqlite3.Row) -> Chat:
    keys = row.keys()
    return Chat(
        chat_id=row["chat_id"], title=row["title"], session_id=row["session_id"],
        project_id=row["project_id"] if "project_id" in keys else None,
        created_at=row["created_at"], updated_at=row["updated_at"],
        archived_at=row["archived_at"], provider=row["provider"],
        model=row["model"], token_estimate=row["token_estimate"],
        pinned=bool(row["pinned"]) if "pinned" in keys else False,
        message_count=row["message_count"] if "message_count" in keys else 0,
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
