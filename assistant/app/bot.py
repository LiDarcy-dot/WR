from __future__ import annotations

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.actions.apply import apply_action, format_action_card
from app.actions.models import ACTION_TYPES
from app.config import Settings
from app.db import connect, init_db
from app.db import repo
from app.llm.lm_studio import LMStudioClient
from app.storage_layout import ensure_data_layout

log = logging.getLogger(__name__)


def owner_only(settings: Settings):
    async def decorator(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != settings.telegram_owner_id:
            if update.effective_message:
                await update.effective_message.reply_text("Доступ запрещён.")
            return False
        return True

    return decorator


def build_confirm_keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Сохранить", callback_data=f"ok:{action_id}"
                ),
                InlineKeyboardButton(
                    "Отмена", callback_data=f"cancel:{action_id}"
                ),
            ]
        ]
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_user and update.effective_user.id != settings.telegram_owner_id:
        await update.effective_message.reply_text("Доступ запрещён.")
        return
    await update.effective_message.reply_text(
        "Локальный ассистент WR на связи.\n"
        "Пиши свободно. Команды: /status /pause /resume"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_user.id != settings.telegram_owner_id:
        return
    conn = context.application.bot_data["db"]
    lm: LMStudioClient = context.application.bot_data["lm"]
    paused = repo.is_paused(conn)
    reason = repo.get_state(conn, "pause_reason", "")
    lm_ok = await lm.healthcheck()
    await update.effective_message.reply_text(
        "Статус:\n"
        f"— пауза: {'да' if paused else 'нет'}"
        + (f" ({reason})" if paused and reason else "")
        + "\n"
        f"— LM Studio: {'ok' if lm_ok else 'недоступна'}\n"
        f"— модель: {settings.lm_studio_model}\n"
        f"— данные: {settings.assistant_data_dir}"
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_user.id != settings.telegram_owner_id:
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, True, "manual")
    conn.commit()
    await update.effective_message.reply_text(
        "Ассистент на паузе. Модель не вызываю. /resume чтобы продолжить."
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_user.id != settings.telegram_owner_id:
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, False)
    conn.commit()
    await update.effective_message.reply_text("Снял паузу. Можно писать.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not update.effective_user or update.effective_user.id != settings.telegram_owner_id:
        return
    if not update.effective_message or not update.effective_message.text:
        return

    conn = context.application.bot_data["db"]
    if repo.is_paused(conn):
        await update.effective_message.reply_text(
            "Сейчас пауза (игра/ручная). Нажми /resume или выйди из игры."
        )
        return

    lm: LMStudioClient = context.application.bot_data["lm"]
    system_prompt = repo.get_active_persona(conn)
    try:
        reply = await lm.chat(
            system_prompt=system_prompt,
            user_text=update.effective_message.text,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("LM Studio error")
        await update.effective_message.reply_text(
            f"Не смог достучаться до LM Studio: {exc}"
        )
        return

    if reply.mode == "propose_action" and reply.action_type in ACTION_TYPES:
        action_id = repo.create_pending_action(
            conn,
            update.effective_chat.id,
            reply.action_type,
            reply.payload,
        )
        conn.commit()
        card = format_action_card(reply.action_type, reply.payload)
        text = f"{reply.message}\n\n{card}" if reply.message else card
        await update.effective_message.reply_text(
            text,
            reply_markup=build_confirm_keyboard(action_id),
        )
        return

    await update.effective_message.reply_text(reply.message)


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
    decision, raw_id = data.split(":", 1)
    try:
        action_id = int(raw_id)
    except ValueError:
        return

    conn = context.application.bot_data["db"]
    pending = repo.get_pending_action(conn, action_id)
    if not pending:
        await query.edit_message_text("Эта карточка уже обработана или устарела.")
        return

    if decision == "cancel":
        repo.resolve_pending_action(conn, action_id, "cancelled")
        conn.commit()
        await query.edit_message_text("Отменено. В БД ничего не писал.")
        return

    if decision == "ok":
        import json

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
        await query.edit_message_text(result)


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
