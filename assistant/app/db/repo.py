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
    existing = conn.execute(
        """
        SELECT id FROM people
        WHERE lower(display_name) = lower(?)
           OR (relation IS NOT NULL AND lower(relation) = lower(?) AND ? != '')
        ORDER BY id DESC LIMIT 1
        """,
        (display_name, relation or "", relation or ""),
    ).fetchone()
    if existing:
        person_id = int(existing["id"])
        conn.execute(
            """
            UPDATE people
            SET display_name = ?,
                aliases = COALESCE(?, aliases),
                relation = COALESCE(?, relation),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (display_name, aliases, relation, person_id),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO people (display_name, aliases, relation)
            VALUES (?, ?, ?)
            """,
            (display_name, aliases, relation),
        )
        person_id = int(cur.lastrowid)

    if month is not None and day is not None:
        row = conn.execute(
            "SELECT id FROM birthdays WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE birthdays
                SET month = ?, day = ?, year = ?, updated_at = datetime('now'), active = 1
                WHERE person_id = ?
                """,
                (month, day, year, person_id),
            )
        else:
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
            ON CONFLICT(person_id, key) DO UPDATE SET
                label = excluded.label,
                value = excluded.value,
                value_type = excluded.value_type,
                updated_at = datetime('now')
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


def get_latest_pending_action(
    conn: sqlite3.Connection, chat_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM pending_actions
        WHERE chat_id = ? AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (chat_id,),
    ).fetchone()


def list_birthdays(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT p.id AS person_id, p.display_name, p.relation,
                   b.month, b.day, b.year, b.active
            FROM birthdays b
            JOIN people p ON p.id = b.person_id
            WHERE b.active = 1
            ORDER BY b.month, b.day, p.display_name
            """
        ).fetchall()
    )


def list_people(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, display_name, relation, created_at
            FROM people
            ORDER BY id DESC
            """
        ).fetchall()
    )


def get_person(conn: sqlite3.Connection, person_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM people WHERE id = ?",
        (person_id,),
    ).fetchone()


def get_birthday_for_person(
    conn: sqlite3.Connection, person_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM birthdays WHERE person_id = ? AND active = 1",
        (person_id,),
    ).fetchone()


def list_person_attributes(
    conn: sqlite3.Connection, person_id: int
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT key, label, value, value_type
            FROM person_attributes
            WHERE person_id = ?
            ORDER BY id
            """,
            (person_id,),
        ).fetchall()
    )


def list_people_with_birthdays(conn: sqlite3.Connection) -> list[dict]:
    """Unified rows for UI: people left-joined with birthday."""
    rows = conn.execute(
        """
        SELECT
            p.id AS person_id,
            p.display_name,
            p.relation,
            b.month,
            b.day,
            b.year
        FROM people p
        LEFT JOIN birthdays b ON b.person_id = p.id AND b.active = 1
        ORDER BY p.display_name COLLATE NOCASE
        """
    ).fetchall()
    return [dict(r) for r in rows]


def recent_writes_today(
    conn: sqlite3.Connection, timezone_offset_hours: int = 3
) -> dict[str, list[sqlite3.Row]]:
    """SQLite stores UTC-ish datetime('now'); compare by local date string YYYY-MM-DD via modifier."""
    # Use 'localtime' if available; also match date prefix on created_at
    people = list(
        conn.execute(
            """
            SELECT id, display_name, relation, created_at
            FROM people
            WHERE date(created_at, 'localtime') = date('now', 'localtime')
               OR date(created_at) = date('now', 'localtime')
               OR created_at LIKE date('now', 'localtime') || '%'
            ORDER BY id DESC
            """
        ).fetchall()
    )
    birthdays = list(
        conn.execute(
            """
            SELECT p.display_name, b.day, b.month, b.year, b.created_at
            FROM birthdays b
            JOIN people p ON p.id = b.person_id
            WHERE date(b.created_at, 'localtime') = date('now', 'localtime')
               OR date(b.created_at) = date('now', 'localtime')
               OR b.created_at LIKE date('now', 'localtime') || '%'
            ORDER BY b.id DESC
            """
        ).fetchall()
    )
    reminders = list(
        conn.execute(
            """
            SELECT id, title, fire_at AS when_at, created_at, 'one_shot' AS kind
            FROM reminders_one_shot
            WHERE date(created_at, 'localtime') = date('now', 'localtime')
               OR created_at LIKE date('now', 'localtime') || '%'
            UNION ALL
            SELECT id, title, next_fire_at AS when_at, created_at, 'recurring' AS kind
            FROM reminders_recurring
            WHERE date(created_at, 'localtime') = date('now', 'localtime')
               OR created_at LIKE date('now', 'localtime') || '%'
            ORDER BY created_at DESC
            """
        ).fetchall()
    )
    applied = list(
        conn.execute(
            """
            SELECT id, action_type, payload_json, resolved_at, created_at
            FROM pending_actions
            WHERE status = 'applied'
              AND (
                date(resolved_at, 'localtime') = date('now', 'localtime')
                OR resolved_at LIKE date('now', 'localtime') || '%'
              )
            ORDER BY id DESC
            """
        ).fetchall()
    )
    return {
        "people": people,
        "birthdays": birthdays,
        "reminders": reminders,
        "applied_actions": applied,
    }


def add_chat_message(
    conn: sqlite3.Connection, chat_id: int, role: str, content: str
) -> None:
    conn.execute(
        """
        INSERT INTO chat_messages (chat_id, role, content)
        VALUES (?, ?, ?)
        """,
        (chat_id, role, content[:8000]),
    )


def get_chat_history(
    conn: sqlite3.Connection, chat_id: int, limit: int = 12
) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT role, content FROM chat_messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (chat_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def build_memory_block(conn: sqlite3.Connection, timezone: str = "Europe/Moscow") -> str:
    from app.memory.formatters import (
        format_birthday_line,
        today_in_tz,
    )

    today = today_in_tz(timezone)
    bdays = list_birthdays(conn)
    people = list_people(conn)
    lines = [
        "ФАКТЫ ИЗ ЛОКАЛЬНОЙ БД (это правда, не выдумывай иное):",
        f"Сегодня: {today.isoformat()}",
        f"Людей в базе: {len(people)}",
        f"Дней рождения: {len(bdays)}",
    ]
    if bdays:
        ordered = sorted(
            bdays,
            key=lambda r: __import__(
                "app.memory.formatters", fromlist=["days_until_next_birthday"]
            ).days_until_next_birthday(r["month"], r["day"], today),
        )
        lines.append("Дни рождения (ближайшие первыми):")
        for r in ordered[:30]:
            lines.append(
                format_birthday_line(
                    r["display_name"],
                    r["month"],
                    r["day"],
                    r["year"],
                    r["relation"],
                    today,
                )
            )
    else:
        lines.append("Дней рождения пока нет.")
    if people:
        lines.append("Люди:")
        for p in people[:40]:
            rel = f" ({p['relation']})" if p["relation"] else ""
            lines.append(f"• id={p['id']} {p['display_name']}{rel}")
    return "\n".join(lines)


def snooze_one_shot(
    conn: sqlite3.Connection, reminder_id: int, until_iso: str
) -> None:
    conn.execute(
        """
        UPDATE reminders_one_shot
        SET status = 'snoozed',
            snooze_until = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (until_iso, reminder_id),
    )
    conn.execute(
        """
        INSERT INTO reminder_events (
            reminder_kind, reminder_id, planned_at, user_action, action_at, snooze_minutes
        ) VALUES ('one_shot', ?, ?, 'snoozed', datetime('now'), NULL)
        """,
        (reminder_id, until_iso),
    )


def mark_one_shot_done(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute(
        """
        UPDATE reminders_one_shot
        SET status = 'done', updated_at = datetime('now')
        WHERE id = ?
        """,
        (reminder_id,),
    )
    conn.execute(
        """
        INSERT INTO reminder_events (
            reminder_kind, reminder_id, planned_at, user_action, action_at
        ) VALUES ('one_shot', ?, datetime('now'), 'done', datetime('now'))
        """,
        (reminder_id,),
    )


def due_one_shots(conn: sqlite3.Connection, now_iso: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM reminders_one_shot
            WHERE
              (status = 'scheduled' AND fire_at <= ?)
              OR (status = 'snoozed' AND snooze_until IS NOT NULL AND snooze_until <= ?)
            ORDER BY id
            LIMIT 20
            """,
            (now_iso, now_iso),
        ).fetchall()
    )


def due_recurring(conn: sqlite3.Connection, now_iso: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM reminders_recurring
            WHERE status = 'active'
              AND next_fire_at IS NOT NULL
              AND next_fire_at <= ?
            ORDER BY id
            LIMIT 20
            """,
            (now_iso,),
        ).fetchall()
    )


def mark_one_shot_sent(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute(
        """
        UPDATE reminders_one_shot
        SET status = 'sent', updated_at = datetime('now')
        WHERE id = ?
        """,
        (reminder_id,),
    )


def bump_recurring_next(
    conn: sqlite3.Connection, reminder_id: int, next_iso: str
) -> None:
    conn.execute(
        """
        UPDATE reminders_recurring
        SET next_fire_at = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (next_iso, reminder_id),
    )


from app.files.store import ensure_files_schema


def ensure_runtime_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    ensure_files_schema(conn)
    # Refresh default persona so old installs learn about the DB
    conn.execute(
        """
        UPDATE persona_presets
        SET system_prompt = ?, updated_at = datetime('now')
        WHERE name = 'default'
        """,
        (
            """Ты локальный личный ассистент на ПК пользователя.
Отвечай по-русски, кратко и по делу.
У тебя ЕСТЬ локальная база SQLite: люди, дни рождения, напоминания, ЖКХ, файлы.
Файлы в хранилище сохраняются только по явной просьбе пользователя (сессия приёма).
Вопросы по мануалам/файлам пользователь задаёт отдельно — программа сама подтянет фрагменты.
Факты из блока «ФАКТЫ ИЗ ЛОКАЛЬНОЙ БД» — достоверны: опирайся на них.
Не говори, что у тебя нет памяти или базы — она есть.
Пользователь пишет свободно, с ошибками — понимай смысл.
Чтобы СОХРАНИТЬ новые данные — верни JSON propose_action (не обычный текст «подтверди»).
Подтверждение пользователь даст кнопкой, «Да», «+» или голосом — это делает программа.
Не выдумывай факты, которых нет в БД и которые пользователь не сообщал.
""",
        ),
    )
    conn.commit()
