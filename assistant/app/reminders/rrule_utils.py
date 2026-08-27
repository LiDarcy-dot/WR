from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr


def humanize_recurrence(
    rrule: str,
    dtstart: str,
    time_of_day: str,
    timezone: str = "Europe/Moscow",
) -> str:
    """Короткое русское описание правила для карточки подтверждения."""
    start = datetime.fromisoformat(dtstart)
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(timezone))
    rule = rrulestr(rrule, dtstart=start)
    # dateutil __str__ is English-ish; keep practical summary for v1
    return (
        f"Правило: {rrule}\n"
        f"Старт серии: {start.date().isoformat()}\n"
        f"Время: {time_of_day} ({timezone})\n"
        f"Ближайшие: "
        + ", ".join(d.strftime("%d.%m.%Y") for d in rule[:3])
    )


def next_occurrence(
    rrule: str,
    dtstart: str,
    after: datetime | None = None,
    timezone: str = "Europe/Moscow",
) -> datetime:
    tz = ZoneInfo(timezone)
    start = datetime.fromisoformat(dtstart)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    now = after or datetime.now(tz=tz)
    rule = rrulestr(rrule, dtstart=start)
    nxt = rule.after(now, inc=False)
    if nxt is None:
        raise ValueError("У правила нет следующей даты")
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt
