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
            [
                InlineKeyboardButton("Календарь", callback_data="cal:today"),
                InlineKeyboardButton("Скоро", callback_data="cal:week"),
            ],
            [
                InlineKeyboardButton("Люди", callback_data="menu:people"),
                InlineKeyboardButton("Напомнить", callback_data="menu:reminders"),
            ],
            [
                InlineKeyboardButton("Поиск", callback_data="menu:web"),
                InlineKeyboardButton("Пауза", callback_data="ctl:pause"),
            ],
            [InlineKeyboardButton("Статус", callback_data="ctl:status")],
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
        "Пиши как удобно — запишу после подтверждения "
        "(кнопка, «да» или «+»).\n"
        "Календарь и «скоро» — кнопки ниже.\n"
        "Поиск в сети: «найди в инете …» / «погугли …».\n"
        "Панель на ПК: http://127.0.0.1:8765"
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
        "web": (
            "<b>Поиск в интернете</b>\n"
            "Напиши, например:\n"
            "<i>найди в инете топ-3 android с 1тб до 50к с доставкой в Москве</i>\n"
            "или: <i>погугли …</i>"
        ),
    }
    return tips.get(section, "Меню")


def people_list_html(people: list[dict], today: date) -> str:
    from app.memory.formatters import MONTHS_RU, days_until_next_birthday

    with_bd = [p for p in people if p.get("month") and p.get("day")]
    without = [p for p in people if not (p.get("month") and p.get("day"))]
    with_bd.sort(
        key=lambda p: days_until_next_birthday(int(p["month"]), int(p["day"]), today)
    )

    lines = [
        f"<b>Люди</b> · {len(people)}"
        + (f" · др {len(with_bd)}" if with_bd else ""),
        "",
    ]

    if with_bd:
        lines.append("<b>дни рождения</b>")
        for p in with_bd:
            month, day = int(p["month"]), int(p["day"])
            delta = days_until_next_birthday(month, day, today)
            when = f"{day} {MONTHS_RU[month]}"
            name = esc(p["display_name"])
            rel = f" · {esc(p['relation'])}" if p.get("relation") else ""
            year = p.get("year")
            age = ""
            if year:
                nxt = today.year - int(year)
                try:
                    bthis = date(today.year, month, day)
                except ValueError:
                    bthis = date(today.year, month, min(day, 28))
                if bthis < today:
                    nxt += 1
                age = f" · {nxt}"
            if delta == 0:
                soon = "сегодня"
            elif delta == 1:
                soon = "завтра"
            else:
                soon = f"через {delta} дн."
            lines.append(f"<b>{name}</b>{rel}")
            lines.append(f"  {when}{age} · <i>{soon}</i>")
        lines.append("")

    if without:
        lines.append("<b>без даты</b>")
        for p in without:
            name = esc(p["display_name"])
            rel = f" · {esc(p['relation'])}" if p.get("relation") else ""
            lines.append(f"{name}{rel}")
        lines.append("")

    if not people:
        lines.append("Пока никого нет.")
        lines.append("<i>напиши: др папы 25.05.1970</i>")
    else:
        lines.append("<i>карточка — кнопка с именем ниже</i>")

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    return text


def people_keyboard(people: list[dict], today: date) -> InlineKeyboardMarkup:
    from app.memory.formatters import days_until_next_birthday

    with_bd = [p for p in people if p.get("month") and p.get("day")]
    with_bd.sort(
        key=lambda p: days_until_next_birthday(int(p["month"]), int(p["day"]), today)
    )
    without = [p for p in people if not (p.get("month") and p.get("day"))]
    ordered = with_bd + without

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in ordered[:24]:
        label = str(p["display_name"])[:18]
        row.append(
            InlineKeyboardButton(label, callback_data=f"p:view:{p['person_id']}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("обновить", callback_data="menu:people"),
            InlineKeyboardButton("календарь", callback_data="cal:today"),
        ]
    )
    rows.append([InlineKeyboardButton("меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def person_card_html(person: dict, attrs: list[dict], today: date) -> str:
    from app.memory.formatters import MONTHS_RU, days_until_next_birthday

    name = esc(person["display_name"])
    lines = [f"<b>{name}</b>"]
    if person.get("relation"):
        lines.append(esc(person["relation"]))
    if person.get("month") and person.get("day"):
        month, day = int(person["month"]), int(person["day"])
        delta = days_until_next_birthday(month, day, today)
        when = f"{day:02d}.{month:02d}"
        if person.get("year"):
            when += f".{int(person['year'])}"
        if delta == 0:
            soon = "сегодня"
        elif delta == 1:
            soon = "завтра"
        else:
            soon = f"через {delta} дн."
        lines.append(f"др {when} · {day} {MONTHS_RU[month]} · <i>{soon}</i>")
    else:
        lines.append("<i>дата рождения не указана</i>")
    for a in attrs:
        lines.append(f"{esc(a.get('label') or a.get('key'))}: {esc(a.get('value'))}")
    return "\n".join(lines)


def person_keyboard(person_id: int, month: int | None, day: int | None, year: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if month and day:
        # jump to that day in current/next occurrence year for calendar
        from datetime import date as date_cls

        today = date_cls.today()
        y = today.year
        try:
            if date_cls(y, month, day) < today:
                y += 1
        except ValueError:
            pass
        rows.append(
            [
                InlineKeyboardButton(
                    "день в календаре",
                    callback_data=f"cal:d:{y:04d}-{month:02d}-{day:02d}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("к списку", callback_data="menu:people")])
    rows.append([InlineKeyboardButton("меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


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
    rows.append(
        [
            InlineKeyboardButton("скоро", callback_data="cal:week"),
            InlineKeyboardButton("меню", callback_data="menu:home"),
        ]
    )
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


def day_keyboard(day: date, events: list[DayEvent] | None = None) -> InlineKeyboardMarkup:
    iso = day.isoformat()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("добавить", callback_data=f"cal:add:{iso}"),
            InlineKeyboardButton("отложить", callback_data=f"cal:snooze:{iso}"),
        ],
        [
            InlineKeyboardButton(
                "к месяцу",
                callback_data=f"cal:m:{day.year:04d}-{day.month:02d}",
            ),
            InlineKeyboardButton("меню", callback_data="menu:home"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def week_html(agenda: list[tuple[date, list[DayEvent]]]) -> str:
    lines = ["<b>Скоро · 7 дней</b>"]
    for d, events in agenda:
        label = d.strftime("%d.%m")
        if not events:
            lines.append(f"{label} —")
            continue
        titles = ", ".join(esc(e.title) for e in events[:3])
        more = f" +{len(events) - 3}" if len(events) > 3 else ""
        lines.append(f"{label} · {titles}{more}")
    return "\n".join(lines)


def week_keyboard(agenda: list[tuple[date, list[DayEvent]]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for d, events in agenda:
        mark = "·" if events else ""
        row.append(
            InlineKeyboardButton(
                f"{d.day}{mark}",
                callback_data=f"cal:d:{d.isoformat()}",
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("календарь", callback_data="cal:today"),
            InlineKeyboardButton("меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def snooze_pick_keyboard(day: date, events: list[DayEvent]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ev in events:
        if ev.kind not in ("reminder", "recurring") or not ev.reminder_id:
            continue
        kind = ev.reminder_kind or "one_shot"
        rid = ev.reminder_id
        title = (ev.title[:18] + "…") if len(ev.title) > 18 else ev.title
        rows.append(
            [InlineKeyboardButton(title, callback_data="cal:noop")]
        )
        rows.append(
            [
                InlineKeyboardButton("+1ч", callback_data=f"rem:s:{kind}:{rid}:60"),
                InlineKeyboardButton("+3ч", callback_data=f"rem:s:{kind}:{rid}:180"),
                InlineKeyboardButton("завтра", callback_data=f"rem:s:{kind}:{rid}:1440"),
            ]
        )
    if not rows:
        rows.append([InlineKeyboardButton("нечего откладывать", callback_data="cal:noop")])
    rows.append(
        [InlineKeyboardButton("назад", callback_data=f"cal:d:{day.isoformat()}")]
    )
    return InlineKeyboardMarkup(rows)
