from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_state(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM assistant_state WHERE key = ?",
        (key,),
    ).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO assistant_state (key, value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = datetime('now')
        """,
        (key, value),
    )


def is_paused(conn: sqlite3.Connection) -> bool:
    return get_state(conn, "paused", "0") == "1"


def set_paused(conn: sqlite3.Connection, paused: bool, reason: str = "") -> None:
    set_state(conn, "paused", "1" if paused else "0")
    set_state(conn, "pause_reason", reason if paused else "")


def get_active_persona(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT system_prompt FROM persona_presets WHERE is_active = 1 LIMIT 1"
    ).fetchone()
    if row:
        return row["system_prompt"]
    return "Ты полезный ассистент. Отвечай по-русски."


def create_pending_action(
    conn: sqlite3.Connection,
    chat_id: int,
    action_type: str,
    payload: dict[str, Any],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO pending_actions (chat_id, action_type, payload_json)
        VALUES (?, ?, ?)
        """,
        (chat_id, action_type, json.dumps(payload, ensure_ascii=False)),
    )
    return int(cur.lastrowid)


def get_pending_action(
    conn: sqlite3.Connection, action_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM pending_actions WHERE id = ? AND status = 'pending'",
        (action_id,),
    ).fetchone()


def resolve_pending_action(
    conn: sqlite3.Connection, action_id: int, status: str
) -> None:
    conn.execute(
        """
        UPDATE pending_actions
        SET status = ?, resolved_at = datetime('now')
        WHERE id = ?
        """,
        (status, action_id),
    )


def upsert_person_with_birthday_and_attrs(
    conn: sqlite3.Connection,
    display_name: str,
    *,
    relation: str | None = None,
    aliases: str | None = None,
    month: int | None = None,
    day: int | None = None,
    year: int | None = None,
    attributes: list[dict[str, str]] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO people (display_name, aliases, relation)
        VALUES (?, ?, ?)
        """,
        (display_name, aliases, relation),
    )
    person_id = int(cur.lastrowid)
    if month is not None and day is not None:
        conn.execute(
            """
            INSERT INTO birthdays (person_id, month, day, year)
            VALUES (?, ?, ?, ?)
            """,
            (person_id, month, day, year),
        )
    for attr in attributes or []:
        conn.execute(
            """
            INSERT INTO person_attributes (person_id, key, label, value, value_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                person_id,
                attr["key"],
                attr.get("label", attr["key"]),
                attr["value"],
                attr.get("value_type", "text"),
            ),
        )
    return person_id


def create_entity_type(
    conn: sqlite3.Connection,
    name: str,
    title: str,
    fields: list[dict[str, Any]],
    description: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO entity_types (name, title, description)
        VALUES (?, ?, ?)
        """,
        (name, title, description),
    )
    entity_type_id = int(cur.lastrowid)
    for i, field in enumerate(fields):
        conn.execute(
            """
            INSERT INTO entity_fields
                (entity_type_id, key, label, field_type, required, sort)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type_id,
                field["key"],
                field.get("label", field["key"]),
                field.get("field_type", "text"),
                1 if field.get("required") else 0,
                field.get("sort", i),
            ),
        )
    return entity_type_id


def create_recurring_reminder(
    conn: sqlite3.Connection,
    *,
    title: str,
    rrule: str,
    dtstart: str,
    time_of_day: str = "10:00",
    timezone: str = "Europe/Moscow",
    body: str | None = None,
    next_fire_at: str | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO reminders_recurring (
            title, body, rrule, dtstart, time_of_day, timezone,
            next_fire_at, source_type, source_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            body,
            rrule,
            dtstart,
            time_of_day,
            timezone,
            next_fire_at,
            source_type,
            source_id,
        ),
    )
    return int(cur.lastrowid)


def create_one_shot_reminder(
    conn: sqlite3.Connection,
    *,
    title: str,
    fire_at: str,
    body: str | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO reminders_one_shot (
            title, body, fire_at, source_type, source_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (title, body, fire_at, source_type, source_id),
    )
    return int(cur.lastrowid)
