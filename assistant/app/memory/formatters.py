from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def days_until_next_birthday(month: int, day: int, today: date) -> int:
    try:
        this_year = date(today.year, month, day)
    except ValueError:
        # 29 Feb -> 28 Feb non-leap
        this_year = date(today.year, month, min(day, 28))
    if this_year < today:
        try:
            nxt = date(today.year + 1, month, day)
        except ValueError:
            nxt = date(today.year + 1, month, min(day, 28))
    else:
        nxt = this_year
    return (nxt - today).days


def format_birthday_line(
    display_name: str,
    month: int,
    day: int,
    year: int | None,
    relation: str | None,
    today: date,
) -> str:
    delta = days_until_next_birthday(month, day, today)
    when = f"{day} {MONTHS_RU[month]}"
    age_bit = ""
    if year:
        next_age = today.year - year
        bday_this = date(today.year, month, min(day, 28))
        if bday_this < today:
            next_age += 1
        age_bit = f", исполнится {next_age}"
    rel = f" ({relation})" if relation else ""
    if delta == 0:
        soon = "сегодня"
    elif delta == 1:
        soon = "завтра"
    else:
        soon = f"через {delta} дн."
    return f"• {display_name}{rel} — {when}{age_bit} — {soon}"


def today_in_tz(timezone: str = "Europe/Moscow") -> date:
    return datetime.now(ZoneInfo(timezone)).date()
