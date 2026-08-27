from __future__ import annotations

import json
import logging

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
from app.config import Settings
from app.db import connect, init_db
from app.db import repo
from app.intent import classify_intent
from app.llm.lm_studio import LMStudioClient
from app.memory.formatters import (
    format_birthday_line,
    today_in_tz,
    days_until_next_birthday,
)
from app.storage_layout import ensure_data_layout
from app.ui import (
    MAIN_REPLY_KEYBOARD,
    MENU_LABELS,
    confirm_keyboard,
    format_action_card_html,
    main_menu_inline,
    menu_section_html,
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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        await update.effective_message.reply_text("Доступ запрещён.")
        return
    await update.effective_message.reply_text(
        welcome_html(),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    await update.effective_message.reply_text(
        "<b>Меню</b>\nВыбери раздел или просто напиши, что нужно.\n"
        "Подтверждение записи: кнопка, <b>Да</b>, <b>+</b> или голосовое.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_inline(),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    lm: LMStudioClient = context.application.bot_data["lm"]
    paused = repo.is_paused(conn)
    reason = repo.get_state(conn, "pause_reason", "")
    lm_ok = await lm.healthcheck()
    n_people = len(repo.list_people(conn))
    n_bd = len(repo.list_birthdays(conn))
    await update.effective_message.reply_text(
        status_html(
            paused=paused,
            reason=reason,
            lm_ok=lm_ok,
            model=settings.lm_studio_model,
            data_dir=str(settings.assistant_data_dir),
        )
        + f"\nВ базе: людей {n_people}, ДР {n_bd}",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, True, "manual")
    conn.commit()
    await update.effective_message.reply_text(
        "⏸ Пауза. Модель не вызываю.\nСнять: «Продолжить» или /resume",
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, False)
    conn.commit()
    await update.effective_message.reply_text(
        "▶️ Снял паузу. Можно писать.",
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


def render_birthdays(conn, timezone: str) -> str:
    today = today_in_tz(timezone)
    rows = repo.list_birthdays(conn)
    if not rows:
        people = repo.list_people(conn)
        if people:
            names = ", ".join(p["display_name"] for p in people[:20])
            return (
                "В таблице дней рождения пусто, но люди есть: "
                f"{names}.\n"
                "Напиши, например: «у папы ДР 25.05.1970» — сохраню дату."
            )
        return "Дней рождения пока нет. Напиши: «запиши ДР …»"
    ordered = sorted(
        rows,
        key=lambda r: days_until_next_birthday(r["month"], r["day"], today),
    )
    lines = ["<b>Дни рождения</b> (от ближайшего):"]
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
    lines = ["<b>Записи за сегодня</b>"]
    if data["people"]:
        lines.append("Люди:")
        for p in data["people"]:
            rel = f" ({p['relation']})" if p["relation"] else ""
            lines.append(f"• {p['display_name']}{rel} [id={p['id']}]")
    if data["birthdays"]:
        lines.append("Дни рождения:")
        for b in data["birthdays"]:
            y = b["year"] or "????"
            lines.append(
                f"• {b['display_name']}: "
                f"{int(b['day']):02d}.{int(b['month']):02d}.{y}"
            )
    if data["reminders"]:
        lines.append("Напоминания:")
        for r in data["reminders"]:
            lines.append(f"• [{r['kind']}] {r['title']}")
    if data["applied_actions"]:
        lines.append(f"Подтверждённых действий: {len(data['applied_actions'])}")
    if len(lines) == 1:
        # fallback: show all people if 'today' filter empty (timezone quirks)
        people = repo.list_people(conn)
        bdays = repo.list_birthdays(conn)
        if not people and not bdays:
            return "За сегодня пусто, и база в целом пустая."
        lines.append("(по фильтру «сегодня» пусто — показываю всё, что есть)")
        for p in people[:30]:
            rel = f" ({p['relation']})" if p["relation"] else ""
            lines.append(f"• человек: {p['display_name']}{rel}")
        for b in bdays[:30]:
            y = b["year"] or "????"
            lines.append(
                f"• ДР: {b['display_name']} "
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
        await update.effective_message.reply_text(f"Ошибка сохранения: {exc}")
        return
    await update.effective_message.reply_text(
        f"✅ {result}\n<i>подтверждено: {via}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def cancel_pending(
    update: Update, context: ContextTypes.DEFAULT_TYPE, pending
) -> None:
    conn = context.application.bot_data["db"]
    repo.resolve_pending_action(conn, pending["id"], "cancelled")
    conn.commit()
    await update.effective_message.reply_text(
        "❌ Отменено. В базу ничего не писал.",
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def _handle_chat_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id

    intent = classify_intent(text)
    pending = repo.get_latest_pending_action(conn, chat_id)

    # Text / + confirmation of latest card
    if intent.kind == "confirm":
        if pending:
            await apply_pending(update, context, pending, via="текст")
            return
        await update.effective_message.reply_text(
            "Сейчас нет карточки на подтверждение. Напиши, что сохранить."
        )
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
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_REPLY_KEYBOARD,
        )
        return

    if intent.kind == "recent_writes":
        await update.effective_message.reply_text(
            render_recent(conn),
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_REPLY_KEYBOARD,
        )
        return

    # Edit mode for card
    edit_id = context.user_data.pop("edit_action_id", None)
    if edit_id is not None:
        old = repo.get_pending_action(conn, edit_id)
        if not old:
            await update.effective_message.reply_text(
                "Карточка устарела. Напиши заново, что сохранить."
            )
            return
        text = (
            "Пользователь хочет ИСПРАВИТЬ черновик перед сохранением.\n"
            f"Тип действия: {old['action_type']}\n"
            f"Старый payload JSON: {old['payload_json']}\n"
            f"Правка пользователя: {text}\n"
            "Верни новый propose_action с исправленным payload."
        )

    if repo.is_paused(conn):
        await update.effective_message.reply_text(
            "⏸ Сейчас пауза. Нажми «Продолжить» или /resume.",
            reply_markup=MAIN_REPLY_KEYBOARD,
        )
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
            "Не достучался до LM Studio.\n"
            f"<code>{esc_err(exc)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if reply.mode == "propose_action" and reply.action_type in ACTION_TYPES:
        if edit_id is not None:
            repo.resolve_pending_action(conn, edit_id, "superseded")
        action_id = repo.create_pending_action(
            conn,
            chat_id,
            reply.action_type,
            reply.payload,
        )
        conn.commit()
        card = format_action_card_html(reply.action_type, reply.payload)
        prefix = f"{reply.message}\n\n" if reply.message else ""
        tip = (
            "\n\nПодтверди: кнопкой <b>Сохранить</b>, словом <b>Да</b>, "
            "знаком <b>+</b> или голосовым сообщением."
        )
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
    # If model asked to confirm in plain text but we have no pending — nudge
    msg = reply.message
    await update.effective_message.reply_text(
        msg,
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    if not update.effective_message or not update.effective_message.text:
        return

    text = update.effective_message.text.strip()

    if text in MENU_LABELS:
        if text == "Меню":
            await cmd_menu(update, context)
            return
        if text == "Статус":
            await cmd_status(update, context)
            return
        if text == "Пауза":
            await cmd_pause(update, context)
            return
        if text == "Продолжить":
            await cmd_resume(update, context)
            return

    await _handle_chat_text(update, context, text)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Voice = confirmation if a card is pending; otherwise ask to type (STT later)."""
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    pending = repo.get_latest_pending_action(conn, update.effective_chat.id)
    if pending:
        await apply_pending(update, context, pending, via="голос")
        return
    await update.effective_message.reply_text(
        "Голосовое пока принимаю как подтверждение карточки.\n"
        "Сейчас карточки нет — напиши текстом, что нужно сделать.\n"
        "(распознавание речи добавим следующим шагом)"
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if update.effective_user.id != settings.telegram_owner_id:
        await query.answer("Нет доступа", show_alert=True)
        return

    await query.answer()
    data = query.data or ""
    if ":" not in data:
        return
    kind, rest = data.split(":", 1)

    if kind == "menu":
        await query.edit_message_text(
            menu_section_html(rest),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_inline(),
        )
        return

    try:
        action_id = int(rest)
    except ValueError:
        return

    conn = context.application.bot_data["db"]
    pending = repo.get_pending_action(conn, action_id)
    if not pending:
        await query.edit_message_text("Эта карточка уже обработана или устарела.")
        return

    if kind == "cancel":
        repo.resolve_pending_action(conn, action_id, "cancelled")
        conn.commit()
        await query.edit_message_text("❌ Отменено. В базу ничего не писал.")
        return

    if kind == "edit":
        context.user_data["edit_action_id"] = action_id
        await query.edit_message_text(
            "✏️ Напиши, что исправить в карточке одним сообщением.\n"
            "Пример: <i>год рождения 1999, вишлист другая ссылка</i>",
            parse_mode=ParseMode.HTML,
        )
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
            await query.edit_message_text(f"Ошибка сохранения: {exc}")
            return
        await query.edit_message_text(f"✅ {result}")


def create_app(settings: Settings) -> Application:
    ensure_data_layout(settings.assistant_data_dir)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    repo.ensure_runtime_schema(conn)
    lm = LMStudioClient(settings.lm_studio_base_url, settings.lm_studio_model)

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = conn
    application.bot_data["lm"] = lm

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)
    )
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
