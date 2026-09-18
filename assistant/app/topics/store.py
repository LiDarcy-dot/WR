from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

GENERAL_THREAD_ID = 1


def ensure_topics_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forum_topics (
            chat_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            mode TEXT NOT NULL,
            created_by INTEGER,
            is_general INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (chat_id, thread_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_hello_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            delete_at TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def upsert_topic(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    thread_id: int,
    title: str,
    mode: str,
    created_by: int | None = None,
    is_general: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO forum_topics (
            chat_id, thread_id, title, mode, created_by, is_general,
            first_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(chat_id, thread_id) DO UPDATE SET
            title = excluded.title,
            mode = excluded.mode,
            created_by = COALESCE(excluded.created_by, forum_topics.created_by),
            is_general = excluded.is_general,
            updated_at = datetime('now')
        """,
        (
            chat_id,
            thread_id,
            title,
            mode,
            created_by,
            1 if is_general else 0,
        ),
    )


def list_topics(conn: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM forum_topics
            WHERE chat_id = ?
            ORDER BY is_general DESC, title COLLATE NOCASE
            """,
            (chat_id,),
        ).fetchall()
    )


def get_topic(
    conn: sqlite3.Connection, chat_id: int, thread_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM forum_topics
        WHERE chat_id = ? AND thread_id = ?
        """,
        (chat_id, thread_id),
    ).fetchone()


def record_hello_message(
    conn: sqlite3.Connection,
    *,
    chat_id: int,
    thread_id: int,
    message_id: int,
    ttl_hours: int = 24,
) -> None:
    delete_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    conn.execute(
        """
        INSERT INTO topic_hello_messages (
            chat_id, thread_id, message_id, delete_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            chat_id,
            thread_id,
            message_id,
            delete_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        ),
    )


def due_hello_deletions(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[sqlite3.Row]:
    now = now or datetime.now(timezone.utc)
    stamp = now.replace(tzinfo=None).isoformat(timespec="seconds")
    return list(
        conn.execute(
            """
            SELECT * FROM topic_hello_messages
            WHERE deleted = 0 AND delete_at <= ?
            ORDER BY id
            LIMIT 50
            """,
            (stamp,),
        ).fetchall()
    )


def mark_hello_deleted(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute(
        "UPDATE topic_hello_messages SET deleted = 1 WHERE id = ?",
        (row_id,),
    )


def topic_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}
