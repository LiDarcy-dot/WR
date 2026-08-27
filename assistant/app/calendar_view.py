from __future__ import annotations

import calendar
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from app.db import repo
from app.memory.formatters import MONTHS_RU


@dataclass
class DayEvent:
    kind: str  # birthday | reminder | recurring
    title: str
    detail: str = ""
    reminder_id: int | None = None
    reminder_kind: str | None = None  # one_shot | recurring


def _parse_fire_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def events_for_month(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    timezone: str = "Europe/Moscow",
) -> dict[int, list[DayEvent]]:
    """Map day-of-month -> events in that month."""
    out: dict[int, list[DayEvent]] = defaultdict(list)

    for row in repo.list_birthdays(conn):
        if int(row["month"]) != month:
            continue
        day = int(row["day"])
        try:
            date(year, month, day)
        except ValueError:
            continue
        name = row["display_name"]
        rel = f" ({row['relation']})" if row["relation"] else ""
        y = row["year"]
        age = f", {year - y}" if y else ""
        out[day].append(
            DayEvent("birthday", f"ДР: {name}{rel}", f"{day} {MONTHS_RU[month]}{age}")
        )

    for row in conn.execute(
        """
        SELECT id, title, body, fire_at, status, snooze_until
        FROM reminders_one_shot
        WHERE status IN ('scheduled', 'snoozed', 'sent')
        """
    ).fetchall():
        d = _parse_fire_date(row["fire_at"])
        if row["status"] == "snoozed":
            d = _parse_fire_date(row["snooze_until"]) or d
        if d and d.year == year and d.month == month:
            out[d.day].append(
                DayEvent(
                    "reminder",
                    row["title"],
                    (row["body"] or "")[:120],
                    reminder_id=int(row["id"]),
                    reminder_kind="one_shot",
                )
            )

    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    for row in conn.execute(
        """
        SELECT id, title, body, rrule, dtstart, time_of_day, timezone, status
        FROM reminders_recurring
        WHERE status = 'active'
        """
    ).fetchall():
        try:
            start = datetime.fromisoformat(row["dtstart"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=ZoneInfo(row["timezone"] or timezone))
            rule = rrulestr(row["rrule"], dtstart=start)
            for occ in rule.between(
                datetime.combine(month_start, datetime.min.time(), tzinfo=start.tzinfo),
                datetime.combine(month_end, datetime.max.time(), tzinfo=start.tzinfo),
                inc=True,
            ):
                out[occ.day].append(
                    DayEvent(
                        "recurring",
                        row["title"],
                        f"{row['time_of_day'] or ''} {(row['body'] or '')}".strip()[:120],
                        reminder_id=int(row["id"]),
                        reminder_kind="recurring",
                    )
                )
        except Exception:
            continue

    return dict(out)


def week_agenda(
    conn: sqlite3.Connection,
    start: date,
    timezone: str = "Europe/Moscow",
    days: int = 7,
) -> list[tuple[date, list[DayEvent]]]:
    result: list[tuple[date, list[DayEvent]]] = []
    # cache months touched
    cache: dict[tuple[int, int], dict[int, list[DayEvent]]] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        key = (d.year, d.month)
        if key not in cache:
            cache[key] = events_for_month(conn, d.year, d.month, timezone)
        result.append((d, cache[key].get(d.day, [])))
    return result



def events_for_day(
    conn: sqlite3.Connection,
    day: date,
    timezone: str = "Europe/Moscow",
) -> list[DayEvent]:
    month_map = events_for_month(conn, day.year, day.month, timezone)
    return month_map.get(day.day, [])


def month_title(year: int, month: int) -> str:
    names = (
        "",
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    )
    return f"{names[month]} {year}"


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    m = month + delta
    y = year
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m


def month_grid(year: int, month: int) -> list[list[int | None]]:
    """Weeks as lists of day numbers (Mon-first), None for empty cells."""
    cal = calendar.Calendar(firstweekday=0)  # Monday
    weeks: list[list[int | None]] = []
    for week in cal.monthdayscalendar(year, month):
        weeks.append([d if d != 0 else None for d in week])
    return weeks
