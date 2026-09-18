from __future__ import annotations

import sqlite3
from typing import Any

from app.db import repo
from app.reminders.rrule_utils import humanize_recurrence, next_occurrence


def format_action_card(action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "upsert_person":
        lines = [
            "Карточка: человек",
            f"Имя: {payload.get('display_name')}",
        ]
        if payload.get("relation"):
            lines.append(f"Кем приходится: {payload['relation']}")
        if payload.get("birthday_day") and payload.get("birthday_month"):
            y = payload.get("birthday_year") or "????"
            lines.append(
                "День рождения: "
                f"{int(payload['birthday_day']):02d}."
                f"{int(payload['birthday_month']):02d}.{y}"
            )
        for attr in payload.get("attributes") or []:
            lines.append(
                f"{attr.get('label', attr.get('key'))}: {attr.get('value')}"
            )
        return "\n".join(lines)

    if action_type == "create_reminder_one_shot":
        return (
            "Карточка: разовое напоминание\n"
            f"Тема: {payload.get('title')}\n"
            f"Когда: {payload.get('fire_at')}\n"
            f"{payload.get('body') or ''}"
        ).strip()

    if action_type == "create_reminder_recurring":
        summary = payload.get("human_summary") or humanize_recurrence(
            payload["rrule"],
            payload["dtstart"],
            payload.get("time_of_day", "10:00"),
            payload.get("timezone", "Europe/Moscow"),
        )
        return (
            "Карточка: регулярное напоминание\n"
            f"Тема: {payload.get('title')}\n"
            f"{summary}\n"
            f"{payload.get('body') or ''}"
        ).strip()

    if action_type == "create_entity_type":
        fields = ", ".join(
            f.get("label", f.get("key", "?")) for f in payload.get("fields") or []
        )
        return (
            "Карточка: новый тип данных\n"
            f"Название: {payload.get('title')} ({payload.get('name')})\n"
            f"Поля: {fields or '—'}"
        )

    return f"Действие: {action_type}\n{payload}"


def apply_action(
    conn: sqlite3.Connection,
    action_type: str,
    payload: dict[str, Any],
    *,
    timezone: str = "Europe/Moscow",
) -> str:
    if action_type == "upsert_person":
        person_id = repo.upsert_person_with_birthday_and_attrs(
            conn,
            payload["display_name"],
            relation=payload.get("relation"),
            aliases=payload.get("aliases"),
            month=payload.get("birthday_month"),
            day=payload.get("birthday_day"),
            year=payload.get("birthday_year"),
            attributes=payload.get("attributes") or [],
        )
        conn.commit()
        return f"Сохранено: человек id={person_id}"

    if action_type == "create_reminder_one_shot":
        rid = repo.create_one_shot_reminder(
            conn,
            title=payload["title"],
            fire_at=payload["fire_at"],
            body=payload.get("body"),
            source_type=payload.get("source_type"),
            source_id=payload.get("source_id"),
        )
        conn.commit()
        return f"Сохранено: разовое напоминание id={rid}"

    if action_type == "create_reminder_recurring":
        nxt = next_occurrence(
            payload["rrule"],
            payload["dtstart"],
            timezone=payload.get("timezone", timezone),
        )
        rid = repo.create_recurring_reminder(
            conn,
            title=payload["title"],
            rrule=payload["rrule"],
            dtstart=payload["dtstart"],
            time_of_day=payload.get("time_of_day", "10:00"),
            timezone=payload.get("timezone", timezone),
            body=payload.get("body"),
            next_fire_at=nxt.isoformat(),
            source_type=payload.get("source_type"),
            source_id=payload.get("source_id"),
        )
        conn.commit()
        return f"Сохранено: регулярное напоминание id={rid}, next={nxt.isoformat()}"

    if action_type == "create_entity_type":
        et_id = repo.create_entity_type(
            conn,
            name=payload["name"],
            title=payload["title"],
            fields=payload.get("fields") or [],
            description=payload.get("description"),
        )
        conn.commit()
        return f"Сохранено: тип сущности id={et_id}"

    raise ValueError(f"Неизвестный action_type: {action_type}")
