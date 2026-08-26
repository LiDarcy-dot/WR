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
from app.llm.lm_studio import LMStudioClient
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
        "<b>Меню</b>\nВыбери раздел или просто напиши, что нужно.",
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
    await update.effective_message.reply_text(
        status_html(
            paused=paused,
            reason=reason,
            lm_ok=lm_ok,
            model=settings.lm_studio_model,
            data_dir=str(settings.assistant_data_dir),
        ),
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
        "⏸ Пауза. Модель не вызываю — можно играть или работать.\n"
        "Снять: кнопка «Продолжить» или /resume",
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


async def _handle_chat_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]

    # Режим «изменить карточку»: следующее сообщение = уточнение для модели
    edit_id = context.user_data.pop("edit_action_id", None)
    if edit_id is not None:
        pending = repo.get_pending_action(conn, edit_id)
        if not pending:
            await update.effective_message.reply_text(
                "Карточка устарела. Напиши заново, что сохранить."
            )
            return
        text = (
            "Пользователь хочет ИСПРАВИТЬ черновик перед сохранением.\n"
            f"Тип действия: {pending['action_type']}\n"
            f"Старый payload JSON: {pending['payload_json']}\n"
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
    try:
        reply = await lm.chat(
            system_prompt=system_prompt,
            user_text=text,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("LM Studio error")
        await update.effective_message.reply_text(
            "Не достучался до LM Studio.\n"
            "Проверь: Local Server на порту 1234, модель загружена.\n"
            f"<code>{esc_err(exc)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if reply.mode == "propose_action" and reply.action_type in ACTION_TYPES:
        # если правили старую карточку — закрываем её как superseded
        if edit_id is not None:
            repo.resolve_pending_action(conn, edit_id, "superseded")
        action_id = repo.create_pending_action(
            conn,
            update.effective_chat.id,
            reply.action_type,
            reply.payload,
        )
        conn.commit()
        card = format_action_card_html(reply.action_type, reply.payload)
        prefix = f"{reply.message}\n\n" if reply.message else ""
        await update.effective_message.reply_text(
            f"{prefix}{card}",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_keyboard(action_id),
        )
        return

    await update.effective_message.reply_text(
        reply.message,
        reply_markup=MAIN_REPLY_KEYBOARD,
    )


def esc_err(exc: Exception) -> str:
    import html as html_mod

    return html_mod.escape(str(exc)[:500])


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
