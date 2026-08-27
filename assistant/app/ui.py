from __future__ import annotations

import html
from datetime import date
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from app.calendar_view import DayEvent, month_grid, month_title, shift_month


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Календарь", callback_data="cal:today")],
            [
                InlineKeyboardButton("Люди", callback_data="menu:people"),
                InlineKeyboardButton("Напомнить", callback_data="menu:reminders"),
            ],
            [
                InlineKeyboardButton("Пауза", callback_data="ctl:pause"),
                InlineKeyboardButton("Статус", callback_data="ctl:status"),
            ],
        ]
    )


def confirm_keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Сохранить", callback_data=f"ok:{action_id}"),
                InlineKeyboardButton("Изменить", callback_data=f"edit:{action_id}"),
            ],
            [InlineKeyboardButton("Отмена", callback_data=f"cancel:{action_id}")],
        ]
    )


def welcome_html() -> str:
    return (
        "Привет.\n\n"
        "Пиши как удобно — запомню после твоего подтверждения "
        "(кнопка, «да» или «+»).\n\n"
        "Открыть календарь и разделы — кнопки ниже, или /menu"
    )


def status_html(
    *,
    paused: bool,
    reason: str,
    lm_ok: bool,
    model: str,
    n_people: int,
    n_bd: int,
) -> str:
    state = "на паузе" if paused else "на связи"
    if paused and reason:
        state += f" ({esc(reason)})"
    brain = "модель отвечает" if lm_ok else "модель молчит"
    return (
        f"Сейчас {state}. {brain}.\n"
        f"Людей: {n_people} · дней рождения: {n_bd}"
    )


def menu_section_html(section: str) -> str:
    tips = {
        "people": (
            "<b>Люди</b>\n"
            "Например: <i>др папы 25.05.1970</i>\n"
            "или: <i>друг Ваня 01.01.1998, вишлист …</i>"
        ),
        "reminders": (
            "<b>Напоминания</b>\n"
            "<i>напомни завтра в 19:00 …</i>\n"
            "Сложные правила тоже можно — покажу как понял."
        ),
        "zhkh": (
            "<b>ЖКХ</b>\n"
            "<i>холодная вода 12.3 за август</i>"
        ),
        "inbox": (
            "<b>Файлы</b>\n"
            "Пока пришли фото текстом-описанием или подожди разбор inbox."
        ),
        "entities": (
            "<b>Свои списки</b>\n"
            "<i>заведи учёт подписок: название, цена, день оплаты</i>"
        ),
        "settings": (
            "<b>Управление</b>\n"
            "Пауза — когда играешь или нужна вся мощность ПК."
        ),
    }
    return tips.get(section, "Меню")


def section_keyboard(section: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Календарь", callback_data="cal:today")],
        [InlineKeyboardButton("Назад", callback_data="menu:home")],
    ]
    if section == "settings":
        rows.insert(
            0,
            [
                InlineKeyboardButton("Пауза", callback_data="ctl:pause"),
                InlineKeyboardButton("Снять паузу", callback_data="ctl:resume"),
            ],
        )
    return InlineKeyboardMarkup(rows)


def format_action_card_html(action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "upsert_person":
        lines = [f"<b>{esc(payload.get('display_name'))}</b>"]
        if payload.get("relation"):
            lines.append(esc(payload["relation"]))
        if payload.get("birthday_day") and payload.get("birthday_month"):
            y = payload.get("birthday_year") or "????"
            lines.append(
                f"др {int(payload['birthday_day']):02d}."
                f"{int(payload['birthday_month']):02d}.{esc(y)}"
            )
        for attr in payload.get("attributes") or []:
            lines.append(
                f"{esc(attr.get('label', attr.get('key')))}: "
                f"{esc(attr.get('value'))}"
            )
        return "\n".join(lines)

    if action_type == "create_reminder_one_shot":
        return (
            f"<b>{esc(payload.get('title'))}</b>\n"
            f"{esc(payload.get('fire_at'))}\n"
            f"{esc(payload.get('body') or '')}"
        ).strip()

    if action_type == "create_reminder_recurring":
        return (
            f"<b>{esc(payload.get('title'))}</b>\n"
            f"{esc(payload.get('human_summary') or payload.get('rrule'))}\n"
            f"{esc(payload.get('body') or '')}"
        ).strip()

    if action_type == "create_entity_type":
        fields = ", ".join(
            esc(f.get("label", f.get("key", "?"))) for f in payload.get("fields") or []
        )
        return f"<b>{esc(payload.get('title'))}</b>\nполя: {fields or '—'}"

    return esc(payload)


def calendar_month_html(year: int, month: int, marked_days: set[int]) -> str:
    title = month_title(year, month)
    n = len(marked_days)
    if n == 0:
        hint = "в этом месяце пока тихо"
    elif n == 1:
        hint = "1 день с событиями"
    else:
        hint = f"{n} дней с событиями"
    return (
        f"<b>{esc(title)}</b>\n"
        f"{hint}\n"
        f"Точка у числа — есть записи. Нажми день."
    )


def calendar_keyboard(
    year: int,
    month: int,
    marked_days: set[int],
    today: date | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(x, callback_data="cal:noop")
            for x in ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
        ]
    )
    for week in month_grid(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day is None:
                row.append(InlineKeyboardButton("·", callback_data="cal:noop"))
                continue
            mark = "·" if day in marked_days else ""
            label = f"{day}{mark}"
            if today and today.year == year and today.month == month and today.day == day:
                label = f"[{day}]{mark}"
            row.append(
                InlineKeyboardButton(
                    label,
                    callback_data=f"cal:d:{year:04d}-{month:02d}-{day:02d}",
                )
            )
        rows.append(row)

    py, pm = shift_month(year, month, -1)
    ny, nm = shift_month(year, month, 1)
    rows.append(
        [
            InlineKeyboardButton("‹", callback_data=f"cal:m:{py:04d}-{pm:02d}"),
            InlineKeyboardButton("сегодня", callback_data="cal:today"),
            InlineKeyboardButton("›", callback_data=f"cal:m:{ny:04d}-{nm:02d}"),
        ]
    )
    rows.append([InlineKeyboardButton("меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def day_detail_html(day: date, events: list[DayEvent]) -> str:
    title = f"{day.day:02d}.{day.month:02d}.{day.year}"
    if not events:
        return f"<b>{title}</b>\nпусто"
    lines = [f"<b>{title}</b>"]
    for ev in events:
        if ev.kind == "birthday":
            prefix = "др"
        elif ev.kind == "recurring":
            prefix = "повтор"
        else:
            prefix = "напоминание"
        extra = f" — {esc(ev.detail)}" if ev.detail else ""
        lines.append(f"• {prefix}: <b>{esc(ev.title)}</b>{extra}")
    return "\n".join(lines)


def day_keyboard(day: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "к месяцу",
                    callback_data=f"cal:m:{day.year:04d}-{day.month:02d}",
                )
            ],
            [InlineKeyboardButton("меню", callback_data="menu:home")],
        ]
    )
