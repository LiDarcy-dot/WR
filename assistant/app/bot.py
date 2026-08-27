from __future__ import annotations

import json
import logging
from datetime import date

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.actions.apply import apply_action
from app.actions.models import ACTION_TYPES
from app.calendar_view import events_for_day, events_for_month
from app.config import Settings
from app.db import connect, init_db
from app.db import repo
from app.intent import classify_intent
from app.llm.lm_studio import LMStudioClient
from app.memory.formatters import (
    days_until_next_birthday,
    format_birthday_line,
    today_in_tz,
)
from app.storage_layout import ensure_data_layout
from app.ui import (
    calendar_keyboard,
    calendar_month_html,
    confirm_keyboard,
    day_detail_html,
    day_keyboard,
    format_action_card_html,
    home_keyboard,
    menu_section_html,
    remove_reply_keyboard,
    section_keyboard,
    status_html,
    welcome_html,
)

log = logging.getLogger(__name__)


def _is_owner(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id == settings.telegram_owner_id)


def esc_err(exc: Exception) -> str:
    import html as html_mod

    return html_mod.escape(str(exc)[:500])


def render_birthdays(conn, timezone: str) -> str:
    today = today_in_tz(timezone)
    rows = repo.list_birthdays(conn)
    if not rows:
        people = repo.list_people(conn)
        if people:
            names = ", ".join(p["display_name"] for p in people[:20])
            return (
                "Дат рождения нет, но люди есть: "
                f"{names}.\n"
                "Напиши, например: «у папы др 25.05.1970»."
            )
        return "Пока пусто. Напиши, чей день рождения добавить."
    ordered = sorted(
        rows,
        key=lambda r: days_until_next_birthday(r["month"], r["day"], today),
    )
    lines = ["Дни рождения — от ближайшего:"]
    for r in ordered:
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
    return "\n".join(lines)


def render_recent(conn) -> str:
    data = repo.recent_writes_today(conn)
    lines = ["За сегодня:"]
    if data["people"]:
        for p in data["people"]:
            rel = f" ({p['relation']})" if p["relation"] else ""
            lines.append(f"• {p['display_name']}{rel}")
    if data["birthdays"]:
        for b in data["birthdays"]:
            y = b["year"] or "????"
            lines.append(
                f"• др {b['display_name']}: "
                f"{int(b['day']):02d}.{int(b['month']):02d}.{y}"
            )
    if data["reminders"]:
        for r in data["reminders"]:
            lines.append(f"• {r['title']}")
    if len(lines) == 1:
        people = repo.list_people(conn)
        bdays = repo.list_birthdays(conn)
        if not people and not bdays:
            return "Пока ничего нет."
        lines = ["В базе сейчас:"]
        for p in people[:30]:
            rel = f" ({p['relation']})" if p["relation"] else ""
            lines.append(f"• {p['display_name']}{rel}")
        for b in bdays[:30]:
            y = b["year"] or "????"
            lines.append(
                f"• др {b['display_name']} "
                f"{int(b['day']):02d}.{int(b['month']):02d}.{y}"
            )
    return "\n".join(lines)


async def apply_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending,
    *,
    via: str,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    payload = json.loads(pending["payload_json"])
    try:
        result = apply_action(
            conn,
            pending["action_type"],
            payload,
            timezone=settings.timezone,
        )
        repo.resolve_pending_action(conn, pending["id"], "applied")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        await update.effective_message.reply_text(f"Не сохранил: {exc}")
        return
    await update.effective_message.reply_text(f"Готово. {result}")


async def cancel_pending(
    update: Update, context: ContextTypes.DEFAULT_TYPE, pending
) -> None:
    conn = context.application.bot_data["db"]
    repo.resolve_pending_action(conn, pending["id"], "cancelled")
    conn.commit()
    await update.effective_message.reply_text("Ок, не записываю.")


def month_payload(conn, settings: Settings, year: int, month: int):
    today = today_in_tz(settings.timezone)
    evmap = events_for_month(conn, year, month, settings.timezone)
    marked = set(evmap.keys())
    text = calendar_month_html(year, month, marked)
    kb = calendar_keyboard(year, month, marked, today=today)
    return text, kb


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        await update.effective_message.reply_text("Нет доступа.")
        return
    # убрать старую нижнюю клавиатуру, если была
    await update.effective_message.reply_text(
        welcome_html(),
        parse_mode=ParseMode.HTML,
        reply_markup=remove_reply_keyboard(),
    )
    await update.effective_message.reply_text(
        "Что открыть?",
        reply_markup=home_keyboard(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    await update.effective_message.reply_text(
        "Что открыть?",
        reply_markup=home_keyboard(),
    )


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    today = today_in_tz(settings.timezone)
    text, kb = month_payload(conn, settings, today.year, today.month)
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=kb
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    lm: LMStudioClient = context.application.bot_data["lm"]
    await update.effective_message.reply_text(
        status_html(
            paused=repo.is_paused(conn),
            reason=repo.get_state(conn, "pause_reason", ""),
            lm_ok=await lm.healthcheck(),
            model=settings.lm_studio_model,
            n_people=len(repo.list_people(conn)),
            n_bd=len(repo.list_birthdays(conn)),
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, True, "manual")
    conn.commit()
    await update.effective_message.reply_text(
        "На паузе. Когда вернёшься — /resume или кнопка в /menu."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, False)
    conn.commit()
    await update.effective_message.reply_text("Снова на связи.")


async def _handle_chat_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id

    intent = classify_intent(text)
    pending = repo.get_latest_pending_action(conn, chat_id)

    if intent.kind == "confirm":
        if pending:
            await apply_pending(update, context, pending, via="текст")
            return
        await update.effective_message.reply_text("Нечего подтверждать.")
        return

    if intent.kind == "cancel":
        if pending:
            await cancel_pending(update, context, pending)
            return
        await update.effective_message.reply_text("Нечего отменять.")
        return

    if intent.kind == "list_birthdays":
        await update.effective_message.reply_text(
            render_birthdays(conn, settings.timezone),
            reply_markup=home_keyboard(),
        )
        return

    if intent.kind == "recent_writes":
        await update.effective_message.reply_text(
            render_recent(conn),
            reply_markup=home_keyboard(),
        )
        return

    low = text.lower()
    if "календар" in low:
        await cmd_calendar(update, context)
        return

    edit_id = context.user_data.pop("edit_action_id", None)
    if edit_id is not None:
        old = repo.get_pending_action(conn, edit_id)
        if not old:
            await update.effective_message.reply_text("Карточка уже неактуальна.")
            return
        text = (
            "Пользователь хочет ИСПРАВИТЬ черновик перед сохранением.\n"
            f"Тип действия: {old['action_type']}\n"
            f"Старый payload JSON: {old['payload_json']}\n"
            f"Правка пользователя: {text}\n"
            "Верни новый propose_action с исправленным payload."
        )

    if repo.is_paused(conn):
        await update.effective_message.reply_text("Сейчас пауза. /resume")
        return

    await update.effective_message.chat.send_action(ChatAction.TYPING)
    lm: LMStudioClient = context.application.bot_data["lm"]
    system_prompt = repo.get_active_persona(conn)
    memory = repo.build_memory_block(conn, settings.timezone)
    history = repo.get_chat_history(conn, chat_id, limit=12)
    repo.add_chat_message(conn, chat_id, "user", text)
    conn.commit()

    try:
        reply = await lm.chat(
            system_prompt=system_prompt + "\n\n" + memory,
            user_text=text,
            history=history,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("LM Studio error")
        await update.effective_message.reply_text(
            f"Модель не ответила.\n<code>{esc_err(exc)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if reply.mode == "propose_action" and reply.action_type in ACTION_TYPES:
        if edit_id is not None:
            repo.resolve_pending_action(conn, edit_id, "superseded")
        action_id = repo.create_pending_action(
            conn, chat_id, reply.action_type, reply.payload
        )
        conn.commit()
        card = format_action_card_html(reply.action_type, reply.payload)
        prefix = f"{reply.message}\n\n" if reply.message else ""
        tip = "\n\nСохранить? Кнопка, «да» или «+»."
        out = f"{prefix}{card}{tip}"
        repo.add_chat_message(conn, chat_id, "assistant", out)
        conn.commit()
        await update.effective_message.reply_text(
            out,
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_keyboard(action_id),
        )
        return

    repo.add_chat_message(conn, chat_id, "assistant", reply.message)
    conn.commit()
    await update.effective_message.reply_text(reply.message)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    if not update.effective_message or not update.effective_message.text:
        return
    await _handle_chat_text(update, context, update.effective_message.text.strip())


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    pending = repo.get_latest_pending_action(conn, update.effective_chat.id)
    if pending:
        await apply_pending(update, context, pending, via="голос")
        return
    await update.effective_message.reply_text(
        "Голосом пока только подтверждаю карточки. Напиши текстом."
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if update.effective_user.id != settings.telegram_owner_id:
        await query.answer("Нет доступа", show_alert=True)
        return

    data = query.data or ""
    conn = context.application.bot_data["db"]

    if data == "cal:noop":
        await query.answer()
        return

    await query.answer()

    if data.startswith("cal:"):
        await _on_calendar(query, context, data)
        return

    if data.startswith("ctl:"):
        action = data.split(":", 1)[1]
        if action == "pause":
            repo.set_paused(conn, True, "manual")
            conn.commit()
            await query.edit_message_text("На паузе.")
            return
        if action == "resume":
            repo.set_paused(conn, False)
            conn.commit()
            await query.edit_message_text("Снова на связи.")
            return
        if action == "status":
            lm: LMStudioClient = context.application.bot_data["lm"]
            await query.edit_message_text(
                status_html(
                    paused=repo.is_paused(conn),
                    reason=repo.get_state(conn, "pause_reason", ""),
                    lm_ok=await lm.healthcheck(),
                    model=settings.lm_studio_model,
                    n_people=len(repo.list_people(conn)),
                    n_bd=len(repo.list_birthdays(conn)),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(),
            )
            return

    if data.startswith("menu:"):
        section = data.split(":", 1)[1]
        if section == "home":
            await query.edit_message_text("Что открыть?", reply_markup=home_keyboard())
            return
        await query.edit_message_text(
            menu_section_html(section),
            parse_mode=ParseMode.HTML,
            reply_markup=section_keyboard(section),
        )
        return

    if ":" not in data:
        return
    kind, rest = data.split(":", 1)
    try:
        action_id = int(rest)
    except ValueError:
        return

    pending = repo.get_pending_action(conn, action_id)
    if not pending:
        await query.edit_message_text("Уже обработано.")
        return

    if kind == "cancel":
        repo.resolve_pending_action(conn, action_id, "cancelled")
        conn.commit()
        await query.edit_message_text("Ок, не записываю.")
        return

    if kind == "edit":
        context.user_data["edit_action_id"] = action_id
        await query.edit_message_text("Что поправить? Одним сообщением.")
        return

    if kind == "ok":
        payload = json.loads(pending["payload_json"])
        try:
            result = apply_action(
                conn,
                pending["action_type"],
                payload,
                timezone=settings.timezone,
            )
            repo.resolve_pending_action(conn, action_id, "applied")
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            await query.edit_message_text(f"Не сохранил: {exc}")
            return
        await query.edit_message_text(f"Готово. {result}")


async def _on_calendar(query, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    today = today_in_tz(settings.timezone)

    if data == "cal:today":
        text, kb = month_payload(conn, settings, today.year, today.month)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # cal:m:YYYY-MM
    if data.startswith("cal:m:"):
        raw = data[6:]
        year_s, month_s = raw.split("-", 1)
        year, month = int(year_s), int(month_s)
        text, kb = month_payload(conn, settings, year, month)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # cal:d:YYYY-MM-DD
    if data.startswith("cal:d:"):
        day = date.fromisoformat(data[6:])
        events = events_for_day(conn, day, settings.timezone)
        await query.edit_message_text(
            day_detail_html(day, events),
            parse_mode=ParseMode.HTML,
            reply_markup=day_keyboard(day),
        )


def create_app(settings: Settings) -> Application:
    ensure_data_layout(settings.assistant_data_dir)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    repo.ensure_runtime_schema(conn)
    lm = LMStudioClient(settings.lm_studio_base_url, settings.lm_studio_model)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["db"] = conn
    application.bot_data["lm"] = lm

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("calendar", cmd_calendar))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(filters.VOICE, on_voice))
    return application


def run_bot(settings: Settings | None = None) -> None:
    from app.config import load_settings

    settings = settings or load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app(settings)
    log.info("Bot starting; data dir=%s", settings.assistant_data_dir)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
