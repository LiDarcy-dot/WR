from __future__ import annotations

import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


# Нижнее меню всегда под рукой (телефон + ПК)
MAIN_REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Меню"), KeyboardButton("Статус")],
        [KeyboardButton("Пауза"), KeyboardButton("Продолжить")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

MENU_LABELS = {
    "Меню",
    "Статус",
    "Пауза",
    "Продолжить",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Люди и ДР", callback_data="menu:people"),
                InlineKeyboardButton("Напоминания", callback_data="menu:reminders"),
            ],
            [
                InlineKeyboardButton("ЖКХ", callback_data="menu:zhkh"),
                InlineKeyboardButton("Inbox", callback_data="menu:inbox"),
            ],
            [
                InlineKeyboardButton("Данные / сущности", callback_data="menu:entities"),
                InlineKeyboardButton("Настройки", callback_data="menu:settings"),
            ],
        ]
    )


def confirm_keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Сохранить", callback_data=f"ok:{action_id}"),
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{action_id}"),
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:{action_id}"),
            ],
        ]
    )


def welcome_html() -> str:
    return (
        "<b>Ассистент WR</b>\n"
        "Локальный помощник на твоём ПК · чат из Telegram\n\n"
        "Пиши свободно — с ошибками тоже ок.\n"
        "Перед записью в базу пришлю карточку на подтверждение.\n\n"
        "<b>Быстрые кнопки внизу:</b> Меню · Статус · Пауза · Продолжить\n"
        "Или команды: /menu /status /pause /resume"
    )


def status_html(
    *,
    paused: bool,
    reason: str,
    lm_ok: bool,
    model: str,
    data_dir: str,
) -> str:
    pause_line = "⏸ <b>Пауза</b>" if paused else "▶️ <b>Работает</b>"
    if paused and reason:
        pause_line += f" <i>({esc(reason)})</i>"
    lm_line = "🟢 LM Studio доступна" if lm_ok else "🔴 LM Studio недоступна"
    return (
        f"{pause_line}\n"
        f"{lm_line}\n"
        f"Модель: <code>{esc(model)}</code>\n"
        f"Данные: <code>{esc(data_dir)}</code>"
    )


def menu_section_html(section: str) -> str:
    tips = {
        "people": (
            "<b>Люди и дни рождения</b>\n"
            "Пример:\n"
            "<i>день рождения друга Вани 01.01.1998, вишлист https://…</i>\n\n"
            "Сохраняется только после кнопки «Сохранить»."
        ),
        "reminders": (
            "<b>Напоминания</b>\n"
            "Разовое: <i>напомни завтра в 19:00 проверить почту</i>\n"
            "Сложное: можно RRULE — бот покажет правило по-русски перед записью."
        ),
        "zhkh": (
            "<b>ЖКХ</b>\n"
            "Пример: <i>счётчик холодной воды 12.3, подал за август</i>\n"
            "Позже подключим кабинет и фон."
        ),
        "inbox": (
            "<b>Inbox</b>\n"
            "Кидай фото/файлы сюда — сложатся в папку inbox на ПК.\n"
            "(разбор файлов допилим следующим шагом)"
        ),
        "entities": (
            "<b>Свои таблицы</b>\n"
            "Пример: <i>заведи учёт подписок: название, цена, день оплаты</i>"
        ),
        "settings": (
            "<b>Настройки</b>\n"
            "Пауза под игры: кнопка «Пауза» или /pause\n"
            "Снять: «Продолжить» или /resume\n"
            "Веб-панель на ПК — в следующей версии."
        ),
    }
    return tips.get(section, "<b>Меню</b>")


def format_action_card_html(action_type: str, payload: dict[str, Any]) -> str:
    if action_type == "upsert_person":
        lines = ["<b>Карточка · человек</b>", f"Имя: <b>{esc(payload.get('display_name'))}</b>"]
        if payload.get("relation"):
            lines.append(f"Кем: {esc(payload['relation'])}")
        if payload.get("birthday_day") and payload.get("birthday_month"):
            y = payload.get("birthday_year") or "????"
            lines.append(
                "ДР: "
                f"<code>{int(payload['birthday_day']):02d}."
                f"{int(payload['birthday_month']):02d}.{esc(y)}</code>"
            )
        for attr in payload.get("attributes") or []:
            lines.append(
                f"{esc(attr.get('label', attr.get('key')))}: "
                f"{esc(attr.get('value'))}"
            )
        return "\n".join(lines)

    if action_type == "create_reminder_one_shot":
        return (
            "<b>Карточка · разовое напоминание</b>\n"
            f"Тема: <b>{esc(payload.get('title'))}</b>\n"
            f"Когда: <code>{esc(payload.get('fire_at'))}</code>\n"
            f"{esc(payload.get('body') or '')}"
        ).strip()

    if action_type == "create_reminder_recurring":
        return (
            "<b>Карточка · регулярное напоминание</b>\n"
            f"Тема: <b>{esc(payload.get('title'))}</b>\n"
            f"RRULE: <code>{esc(payload.get('rrule'))}</code>\n"
            f"Старт: <code>{esc(payload.get('dtstart'))}</code> "
            f"в <code>{esc(payload.get('time_of_day', '10:00'))}</code>\n"
            f"{esc(payload.get('human_summary') or '')}\n"
            f"{esc(payload.get('body') or '')}"
        ).strip()

    if action_type == "create_entity_type":
        fields = ", ".join(
            esc(f.get("label", f.get("key", "?"))) for f in payload.get("fields") or []
        )
        return (
            "<b>Карточка · новый тип данных</b>\n"
            f"{esc(payload.get('title'))} "
            f"(<code>{esc(payload.get('name'))}</code>)\n"
            f"Поля: {fields or '—'}"
        )

    return f"<b>Действие</b> <code>{esc(action_type)}</code>\n{esc(payload)}"
