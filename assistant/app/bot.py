from __future__ import annotations

import json
import logging
import re
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
from app.config import Settings
from app.db import connect, init_db
from app.db import repo
from app.files import store as file_store
from app.files.ingest import index_file, save_telegram_bytes, try_unlock_pending
from app.files.query import DOCS_SYSTEM, build_docs_context, list_files_html
from app.files.store import category_slug, parse_password_candidates, search_chunks
from app.files import temp_session
from app.intent import classify_intent
from app.llm.lm_studio import LMStudioClient, WEB_SYSTEM
from app.llm.router import ModelRouter, answer_about_image
from app.media.pipeline import analyze_bytes
from app.memory.formatters import (
    days_until_next_birthday,
    format_birthday_line,
    today_in_tz,
)
from app.scheduler import process_due_reminders
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
    people_keyboard,
    people_list_html,
    person_card_html,
    person_keyboard,
    remove_reply_keyboard,
    resume_keyboard,
    section_keyboard,
    snooze_pick_keyboard,
    status_html,
    week_html,
    week_keyboard,
    welcome_html,
)
from app.websearch.engine import format_research_context, gather_research

log = logging.getLogger(__name__)


def _is_owner(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id == settings.telegram_owner_id)


def esc_err(exc: Exception) -> str:
    import html as html_mod

    return html_mod.escape(str(exc)[:500])


def render_birthdays(conn, timezone: str) -> str:
    today = today_in_tz(timezone)
    people = repo.list_people_with_birthdays(conn)
    return people_list_html(people, today)


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
    conn = context.application.bot_data["db"]
    paused = repo.is_paused(conn)
    await update.effective_message.reply_text(
        welcome_html(),
        parse_mode=ParseMode.HTML,
        reply_markup=remove_reply_keyboard(),
    )
    await update.effective_message.reply_text(
        "На паузе. Нажми «Снять паузу»." if paused else "Что открыть?",
        reply_markup=home_keyboard(paused=paused),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    paused = repo.is_paused(conn)
    await update.effective_message.reply_text(
        "На паузе. Нажми «Снять паузу»." if paused else "Что открыть?",
        reply_markup=home_keyboard(paused=paused),
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
    paused = repo.is_paused(conn)
    await update.effective_message.reply_text(
        status_html(
            paused=paused,
            reason=repo.get_state(conn, "pause_reason", ""),
            lm_ok=await lm.healthcheck(),
            model=settings.lm_studio_model,
            n_people=len(repo.list_people(conn)),
            n_bd=len(repo.list_birthdays(conn)),
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(paused=paused),
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, True, "manual")
    conn.commit()
    await update.effective_message.reply_text(
        "На паузе.",
        reply_markup=resume_keyboard(),
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    repo.set_paused(conn, False)
    conn.commit()
    await update.effective_message.reply_text(
        "Снова на связи.",
        reply_markup=home_keyboard(paused=False),
    )


async def _handle_chat_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id

    intent = classify_intent(text)
    pending = repo.get_latest_pending_action(conn, chat_id)

    # Text resume while paused
    low_early = text.lower().replace("ё", "е").strip()
    if repo.is_paused(conn) and low_early in {
        "продолжить",
        "сними паузу",
        "снять паузу",
        "resume",
        "/resume",
        "старт",
        "включись",
        "работай",
    }:
        repo.set_paused(conn, False)
        conn.commit()
        await update.effective_message.reply_text(
            "Снова на связи.",
            reply_markup=home_keyboard(paused=False),
        )
        return

    if intent.kind == "confirm":
        if pending:
            await apply_pending(update, context, pending, via="текст")
            return
        await update.effective_message.reply_text("Нечего подтверждать.")
        return

    if intent.kind == "abort":
        cleared = await _abort_active_sessions(update, context)
        if pending:
            await cancel_pending(update, context, pending)
            return
        if cleared:
            return
        await update.effective_message.reply_text("Нечего отменять.")
        return

    if intent.kind == "cancel":
        if pending:
            await cancel_pending(update, context, pending)
            return
        cleared = await _abort_active_sessions(update, context)
        if cleared:
            return
        await update.effective_message.reply_text("Нечего отменять.")
        return

    if intent.kind == "list_birthdays":
        today = today_in_tz(settings.timezone)
        people = repo.list_people_with_birthdays(conn)
        await update.effective_message.reply_text(
            people_list_html(people, today),
            parse_mode=ParseMode.HTML,
            reply_markup=people_keyboard(people, today),
        )
        return

    if intent.kind == "recent_writes":
        await update.effective_message.reply_text(
            render_recent(conn),
            reply_markup=home_keyboard(paused=repo.is_paused(conn)),
        )
        return

    # --- temporary file read (not saved to library) ---
    temp = temp_session.get_session(context.application.bot_data, chat_id)

    if intent.kind == "temp_read_start":
        # don't keep library ingest open in parallel
        open_ingest = file_store.get_open_ingest(conn, chat_id)
        if open_ingest:
            file_store.close_ingest_session(conn, int(open_ingest["id"]))
            conn.commit()
        temp_session.start_waiting(
            context.application.bot_data, chat_id, note=text
        )
        await update.effective_message.reply_text(
            "Ок. Жду файл — в постоянное хранилище не положу.\n"
            "Прочитаю и отвечу по нему.\n"
            "Передумаешь — «забей» / «отмена»."
        )
        return

    if intent.kind == "temp_read_end" and temp:
        temp_session.clear_session(context.application.bot_data, chat_id)
        await update.effective_message.reply_text(
            "Ок, временный файл закрыл. В хранилище его нет."
        )
        return

    if temp and temp.get("status") == "waiting_file":
        # still waiting — don't search library / don't treat as chat yet
        if intent.kind in {
            "password_candidates",
            "file_password",
            "list_files",
            "ask_docs",
            "web_search",
            "ingest_start",
        }:
            pass  # fall through to those handlers below
        else:
            await update.effective_message.reply_text(
                "Жду файл для временного чтения.\n"
                "Или «забей», если передумал."
            )
            return

    if temp and temp.get("status") in {"ready", "needs_password"}:
        if intent.kind in {
            "ask_docs",
            "list_files",
            "web_search",
            "ingest_start",
            "list_birthdays",
            "recent_writes",
            "password_candidates",
            "file_password",
            "temp_read_start",
        }:
            pass
        elif temp.get("status") == "needs_password":
            await update.effective_message.reply_text(
                "Файл запаролен. Пришли «возможные пароли …» или "
                "«пароль: secret», либо «забей»."
            )
            return
        else:
            await _answer_temp_file(update, context, text)
            return

    # --- file library ---
    open_session = file_store.get_open_ingest(conn, chat_id)

    if intent.kind == "ingest_start":
        # close temp-read if any
        if temp:
            temp_session.clear_session(context.application.bot_data, chat_id)
        cat = category_slug(text)
        sid = file_store.open_ingest_session(
            conn, chat_id, category=cat, title=text[:200]
        )
        conn.commit()
        await update.effective_message.reply_text(
            "Ок, жду файлы.\n"
            f"Папка: <code>{cat}</code>\n"
            "Можно писать комментарии между файлами.\n"
            "Когда закончишь — «готово» или «всё».\n"
            "Передумаешь — «забей».",
            parse_mode=ParseMode.HTML,
        )
        return

    if open_session and intent.kind == "ingest_end":
        file_store.close_ingest_session(conn, int(open_session["id"]))
        rows = file_store.list_files(conn, category=open_session["category"], limit=30)
        conn.commit()
        await update.effective_message.reply_text(
            "Приём файлов закрыт.\n" + list_files_html(rows),
            parse_mode=ParseMode.HTML,
        )
        return

    if open_session and intent.kind not in {
        "confirm",
        "cancel",
        "abort",
        "web_search",
        "list_birthdays",
        "ask_docs",
        "list_files",
        "file_password",
        "password_candidates",
        "ingest_start",
        "temp_read_start",
    }:
        # comment for next file(s)
        file_store.set_pending_comment(conn, int(open_session["id"]), text)
        conn.commit()
        await update.effective_message.reply_text(
            "Комментарий принял — привяжу к следующему файлу."
        )
        return

    if intent.kind == "list_files":
        rows = file_store.list_files(conn, limit=40)
        await update.effective_message.reply_text(
            list_files_html(rows),
            parse_mode=ParseMode.HTML,
        )
        return

    if intent.kind == "file_password":
        await _handle_file_password(update, context, text)
        return

    if intent.kind == "password_candidates":
        await _handle_password_candidates(update, context, text)
        return

    if intent.kind == "ask_docs":
        if repo.is_paused(conn):
            await update.effective_message.reply_text(
                "Сейчас пауза.", reply_markup=resume_keyboard()
            )
            return
        await update.effective_message.reply_text("Смотрю в файлах…")
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        hits = search_chunks(conn, text, limit=14)
        if not hits:
            await update.effective_message.reply_text(
                "В проиндексированных файлах ничего близкого не нашёл.\n"
                "Проверь «какие файлы» или уточни запрос."
            )
            return
        lm: LMStudioClient = context.application.bot_data["lm"]
        ctx = build_docs_context(hits)
        try:
            answer = await lm.chat_plain(
                system_prompt=DOCS_SYSTEM,
                user_text=ctx + f"\n\nВопрос пользователя: {text}",
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"Модель не ответила: {exc}")
            return
        if len(answer) > 3900:
            answer = answer[:3900] + "\n…"
        # append compact sources
        sources = []
        seen = set()
        for h in hits:
            key = (h["original_name"], h["page"])
            if key in seen:
                continue
            seen.add(key)
            sources.append(f"• {h['original_name']} · стр. {h['page'] or '?'}")
            if len(sources) >= 8:
                break
        answer = answer + "\n\nИсточники:\n" + "\n".join(sources)
        if len(answer) > 3900:
            answer = answer[:3900] + "\n…"
        await update.effective_message.reply_text(answer)
        return

    if intent.kind == "web_search":
        if repo.is_paused(conn):
            await update.effective_message.reply_text(
                "Сейчас пауза.",
                reply_markup=resume_keyboard(),
            )
            return
        await update.effective_message.reply_text("Ищу…")
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        lm: LMStudioClient = context.application.bot_data["lm"]
        try:
            hits, pages = await gather_research(text, max_results=6, fetch_top=3)
        except Exception as exc:  # noqa: BLE001
            log.exception("web search failed")
            await update.effective_message.reply_text(
                f"Поиск не вышел: {exc}\nПроверь интернет/VPN на ПК."
            )
            return
        if not hits:
            await update.effective_message.reply_text(
                "Ничего не нашёл. Уточни запрос или проверь сеть на ПК."
            )
            return
        context_block = format_research_context(text, hits, pages)
        try:
            answer = await lm.chat_plain(
                system_prompt=WEB_SYSTEM,
                user_text=context_block
                + "\n\nСформулируй полезный ответ пользователю по его запросу.",
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("web synthesize failed")
            # fallback: just links
            lines = ["Нашёл ссылки, но модель не ответила:", ""]
            for h in hits[:5]:
                lines.append(f"• {h.title}\n{h.url}")
            lines.append(f"\n({esc_err(exc)})")
            await update.effective_message.reply_text("\n".join(lines))
            return
        # Telegram limit
        if len(answer) > 3900:
            answer = answer[:3900] + "\n…"
        repo.add_chat_message(conn, chat_id, "user", text)
        repo.add_chat_message(conn, chat_id, "assistant", answer)
        conn.commit()
        await update.effective_message.reply_text(answer)
        return

    low = text.lower()
    if "календар" in low:
        await cmd_calendar(update, context)
        return
    if low in {"скоро", "что скоро", "на неделе", "эта неделя"} or "что скоро" in low:
        await cmd_soon(update, context)
        return

    edit_id = context.user_data.pop("edit_action_id", None)
    add_date = context.user_data.get("add_on_date")
    if add_date is not None and edit_id is None:
        context.user_data.pop("add_on_date", None)
        # текст = название напоминания на выбранный день
        fire_at = f"{add_date}T10:00:00"
        action_id = repo.create_pending_action(
            conn,
            chat_id,
            "create_reminder_one_shot",
            {"title": text, "fire_at": fire_at, "body": None},
        )
        conn.commit()
        card = format_action_card_html(
            "create_reminder_one_shot",
            {"title": text, "fire_at": fire_at},
        )
        await update.effective_message.reply_text(
            f"{card}\n\nСохранить? Кнопка, «да» или «+».",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_keyboard(action_id),
        )
        return

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
        await update.effective_message.reply_text(
            "Сейчас пауза.",
            reply_markup=resume_keyboard(),
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
    text = update.effective_message.text.strip()
    # Reply to a message with media/text → work with that content
    reply = update.effective_message.reply_to_message
    if reply and text:
        handled = await _handle_reply_to(update, context, text, reply)
        if handled:
            return
    await _handle_chat_text(update, context, text)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    pending = repo.get_latest_pending_action(conn, update.effective_chat.id)
    if pending:
        await apply_pending(update, context, pending, via="голос")
        return
    # otherwise treat as audio attachment for temp/analysis
    await _ingest_media(update, context, kind="voice")


async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ingest_media(update, context, kind="audio")


async def _download_message_media(
    msg,
) -> tuple[bytes, str, str | None] | None:
    """Return (raw, filename, mime) from a Telegram message, or None."""
    if msg.document:
        tg_file = await msg.document.get_file()
        original = msg.document.file_name or f"doc_{msg.document.file_unique_id}"
        mime = msg.document.mime_type
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, mime
    if msg.photo:
        photo = msg.photo[-1]
        tg_file = await photo.get_file()
        original = f"photo_{photo.file_unique_id}.jpg"
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, "image/jpeg"
    if msg.voice:
        tg_file = await msg.voice.get_file()
        original = f"voice_{msg.voice.file_unique_id}.ogg"
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, msg.voice.mime_type or "audio/ogg"
    if msg.audio:
        tg_file = await msg.audio.get_file()
        original = msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, msg.audio.mime_type
    if msg.video:
        tg_file = await msg.video.get_file()
        original = msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, msg.video.mime_type
    if msg.video_note:
        tg_file = await msg.video_note.get_file()
        original = f"videonote_{msg.video_note.file_unique_id}.mp4"
        raw = bytes(await tg_file.download_as_bytearray())
        return raw, original, "video/mp4"
    return None


async def _handle_reply_to(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply
) -> bool:
    """If reply targets media/text, analyze it for this question. Returns True if handled."""
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    router: ModelRouter = context.application.bot_data["router"]
    bot_data = context.application.bot_data

    media = await _download_message_media(reply)
    reply_text = (reply.text or reply.caption or "").strip()

    if not media and not reply_text:
        return False

    # abort phrases still win globally via classify in _handle_chat_text;
    # here we only handle content-bearing replies
    intent = classify_intent(text)
    if intent.kind in {"abort", "cancel", "confirm"}:
        return False

    await update.effective_message.reply_text("Смотрю вложение из ответа…")
    await update.effective_message.chat.send_action(ChatAction.TYPING)

    if media:
        raw, original, mime = media
        if len(raw) > 45 * 1024 * 1024:
            await update.effective_message.reply_text("Файл слишком большой (>45 МБ).")
            return True
        analyzed = await analyze_bytes(
            conn=conn,
            data_root=settings.assistant_data_dir,
            router=router,
            raw=raw,
            original_name=original,
            mime=mime,
        )
        note = text
        if reply_text:
            note = f"{text}\n(подпись/текст исходного: {reply_text[:500]})"
        temp_session.start_waiting(bot_data, chat_id, note=note)
        temp_session.mark_ready(
            bot_data,
            chat_id,
            name=analyzed.name,
            text=analyzed.text,
            path=analyzed.path,
            kind=analyzed.kind,
            image_data_url=analyzed.image_data_url,
            needs_password=analyzed.needs_password,
        )
        if analyzed.needs_password:
            await update.effective_message.reply_text(
                f"{analyzed.summary} Пришли пароль или «возможные пароли …»."
            )
            return True
        await _answer_temp_file(update, context, text)
        return True

    # reply to plain text message
    temp_session.start_waiting(bot_data, chat_id, note=text)
    temp_session.mark_ready(
        bot_data,
        chat_id,
        name="сообщение",
        text=reply_text,
        path=None,
        kind="text",
    )
    await _answer_temp_file(update, context, text)
    return True


def _parse_file_password(text: str) -> tuple[int | None, str | None]:
    """Extract optional file id and password from user text."""
    m = re.search(
        r"пароль\s+(?:к\s+|для\s+|от\s+)?"
        r"(?:файл(?:а|у)?\s+|pdf\s+|id\s+)?"
        r"(?:#|№)?(\d+)?\s*[:\-–]\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        fid = int(m.group(1)) if m.group(1) else None
        pwd = (m.group(2) or "").strip()
        return fid, pwd or None
    m2 = re.search(
        r"пароль\s+(?:к\s+|для\s+|от\s+)?"
        r"(?:файл(?:а|у)?\s+|pdf\s+|id\s+)?"
        r"(?:#|№)?(\d+)\s+(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m2:
        return int(m2.group(1)), (m2.group(2) or "").strip() or None
    return None, None


async def _handle_file_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    file_id, password = _parse_file_password(text)

    temp = temp_session.get_session(context.application.bot_data, chat_id)
    if temp and temp.get("status") == "needs_password" and password and file_id is None:
        if not temp.get("path"):
            await update.effective_message.reply_text("Временный файл потерян — пришли снова.")
            temp_session.clear_session(context.application.bot_data, chat_id)
            return
        body, err = temp_session.unlock_temp_path(temp["path"], password)
        if err == "password":
            await update.effective_message.reply_text("Пароль не подошёл. Ещё вариант?")
            return
        if err:
            await update.effective_message.reply_text(f"Не разобрал: {err}")
            return
        file_store.add_password_candidates(conn, [password], source="temp_unlock")
        conn.commit()
        temp_session.mark_ready(
            context.application.bot_data,
            chat_id,
            name=temp.get("name") or "file",
            text=body,
            path=temp.get("path"),
            needs_password=False,
        )
        await _reply_temp_ready(update, context)
        return

    if not password:
        await update.effective_message.reply_text(
            "Формат: <code>пароль к файлу 12: secret</code>\n"
            "или список: <code>возможные пароли a b c</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    row = None
    if file_id is not None:
        row = file_store.get_file(conn, file_id)
        if not row:
            await update.effective_message.reply_text(f"Файл id={file_id} не найден.")
            return
    else:
        row = file_store.latest_needs_password(conn)
        if not row:
            await update.effective_message.reply_text(
                "Нет файлов, ждущих пароль. Укажи id: «пароль к файлу 12: …»."
            )
            return
        file_id = int(row["id"])

    file_store.set_file_password(conn, file_id, password)
    file_store.add_password_candidates(conn, [password], source="user_exact")
    msg = index_file(conn, settings.assistant_data_dir, file_id)
    conn.commit()
    name = row["original_name"] or f"id={file_id}"
    await update.effective_message.reply_text(f"{name}: {msg}")


async def _handle_password_candidates(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    passwords = parse_password_candidates(text)
    if not passwords:
        await update.effective_message.reply_text(
            "Не разобрал пароли.\n"
            "Пример: <code>возможные пароли pass1 pass2</code>\n"
            "или с новой строки после фразы «возможные пароли».",
            parse_mode=ParseMode.HTML,
        )
        return

    added = file_store.add_password_candidates(conn, passwords, source="user")
    total = len(file_store.list_password_candidates(conn))
    lines = [
        f"Принял пароли: новых {added}, всего в пуле {total}.",
    ]

    temp = temp_session.get_session(context.application.bot_data, chat_id)
    if temp and temp.get("status") == "needs_password" and temp.get("path"):
        for pwd in passwords:
            body, err = temp_session.unlock_temp_path(temp["path"], pwd)
            if err == "password":
                continue
            if err:
                lines.append(f"Временный: {err}")
                break
            temp_session.mark_ready(
                context.application.bot_data,
                chat_id,
                name=temp.get("name") or "file",
                text=body or "",
                path=temp.get("path"),
                needs_password=False,
            )
            lines.append("Временный файл открылся паролем.")
            conn.commit()
            await update.effective_message.reply_text("\n".join(lines))
            if body:
                await _reply_temp_ready(update, context)
            else:
                await update.effective_message.reply_text(
                    "Открыл, но текста нет. «забей» — закрыть."
                )
            return
        lines.append("К временному файлу пароли не подошли.")

    locked = file_store.list_files_needing_password(conn)
    if locked:
        lines.append(f"Пробую на {len(locked)} файлах в хранилище…")
        await update.effective_message.reply_text("\n".join(lines))
        results = try_unlock_pending(conn, settings.assistant_data_dir)
        conn.commit()
        body = "\n".join(results) if results else "Нечего пробовать."
        if len(body) > 3500:
            body = body[:3500] + "\n…"
        await update.effective_message.reply_text(body)
        return

    conn.commit()
    if len(lines) == 1:
        lines.append("Сейчас нет файлов, ждущих пароль — сохраню пул на будущее.")
    await update.effective_message.reply_text("\n".join(lines))


async def _abort_active_sessions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Clear temp-read and/or library ingest. Returns True if something was cleared."""
    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    parts: list[str] = []

    temp = temp_session.get_session(context.application.bot_data, chat_id)
    if temp:
        temp_session.clear_session(context.application.bot_data, chat_id)
        parts.append("временное чтение отменил")

    open_session = file_store.get_open_ingest(conn, chat_id)
    if open_session:
        file_store.close_ingest_session(conn, int(open_session["id"]))
        conn.commit()
        parts.append("приём в хранилище закрыл")

    if not parts:
        return False
    await update.effective_message.reply_text("Ок, " + " и ".join(parts) + ".")
    return True


async def _reply_temp_ready(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update.effective_chat.id
    sess = temp_session.get_session(context.application.bot_data, chat_id)
    if not sess or sess.get("status") != "ready":
        return
    name = sess.get("name") or "файл"
    note = sess.get("note")
    kind = sess.get("kind") or "text"
    body = (sess.get("text") or "").strip()
    lm: LMStudioClient = context.application.bot_data["lm"]

    if not body and not sess.get("image_data_url"):
        await update.effective_message.reply_text(
            f"«{name}» принял временно ({kind}), содержимого пока нет.\n"
            "«забей» — закрыть."
        )
        return

    prompt = (
        f"Временное вложение «{name}» (тип {kind}), не в хранилище.\n"
    )
    if note:
        prompt += f"Просьба пользователя: {note}\n"
    if body:
        prompt += (
            "Ниже распознанное содержимое. Кратко (3–8 предложений) скажи, "
            "что понял и КАК будешь отвечать на вопросы. Не копируй всё подряд.\n\n"
            f"{body[:8000]}"
        )
    else:
        prompt += "Содержимое пока только как файл/картинка без текста. Как будешь помогать?"

    await update.effective_message.chat.send_action(ChatAction.TYPING)
    try:
        answer = await lm.chat_plain(
            system_prompt=temp_session.TEMP_SYSTEM,
            user_text=prompt,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        preview = body[:800] + ("…" if len(body) > 800 else "")
        answer = (
            f"«{name}» принял временно.\n{preview or '(без текста)'}\n"
            f"Модель не ответила ({exc}). Задавай вопросы.\n«забей» — закрыть."
        )
    if len(answer) > 3900:
        answer = answer[:3900] + "\n…"
    answer = answer + "\n\nЗадавай вопросы. Можно ответом (reply) на сообщение с файлом. «забей» — закрыть."
    await update.effective_message.reply_text(answer)


async def _answer_temp_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    chat_id = update.effective_chat.id
    sess = temp_session.get_session(context.application.bot_data, chat_id)
    if not sess or sess.get("status") not in {"ready", "needs_password"}:
        await update.effective_message.reply_text("Временного файла нет.")
        return
    if sess.get("status") == "needs_password":
        await update.effective_message.reply_text(
            "Сначала пароль: «пароль: …» или «возможные пароли …»."
        )
        return

    router: ModelRouter = context.application.bot_data["router"]
    lm: LMStudioClient = context.application.bot_data["lm"]
    await update.effective_message.reply_text("Смотрю во временном вложении…")
    await update.effective_message.chat.send_action(ChatAction.TYPING)

    try:
        if sess.get("kind") == "image" and sess.get("image_data_url"):
            answer = await answer_about_image(
                router,
                data_url=sess["image_data_url"],
                question=text,
                prior_notes=sess.get("text"),
            )
        else:
            answer = await lm.chat_plain(
                system_prompt=temp_session.TEMP_SYSTEM,
                user_text=temp_session.build_temp_context(sess, text),
                temperature=0.2,
            )
    except Exception as exc:  # noqa: BLE001
        await update.effective_message.reply_text(f"Модель не ответила: {exc}")
        return
    if len(answer) > 3900:
        answer = answer[:3900] + "\n…"
    await update.effective_message.reply_text(answer)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ingest_media(update, context, kind="document")


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ingest_media(update, context, kind="photo")


async def _ingest_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, kind: str
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    if not update.effective_message or not update.effective_chat:
        return

    conn = context.application.bot_data["db"]
    chat_id = update.effective_chat.id
    bot_data = context.application.bot_data
    router: ModelRouter = bot_data["router"]
    temp = temp_session.get_session(bot_data, chat_id)
    session = file_store.get_open_ingest(conn, chat_id)

    msg = update.effective_message
    try:
        if kind == "document" and msg.document:
            packed = await _download_message_media(msg)
        elif kind == "photo" and msg.photo:
            packed = await _download_message_media(msg)
        elif kind == "voice" and msg.voice:
            packed = await _download_message_media(msg)
        elif kind == "audio" and msg.audio:
            packed = await _download_message_media(msg)
        else:
            packed = await _download_message_media(msg)
        if not packed:
            await update.effective_message.reply_text("Не понял вложение.")
            return
        raw, original, mime = packed
    except Exception as exc:  # noqa: BLE001
        log.exception("telegram download failed")
        await update.effective_message.reply_text(f"Не скачал файл: {exc}")
        return

    if len(raw) > 45 * 1024 * 1024:
        await update.effective_message.reply_text("Слишком большой файл (>45 МБ).")
        return

    caption = (msg.caption or "").strip() or None

    # Auto ephemeral when not saving to library
    if not session and (
        not temp
        or temp.get("status") not in {"waiting_file", "needs_password", "ready"}
    ):
        temp_session.start_waiting(
            bot_data,
            chat_id,
            note=caption or "временный разбор вложения",
        )
        temp = temp_session.get_session(bot_data, chat_id)

    # --- temporary / ephemeral ---
    if (
        not session
        and temp
        and temp.get("status") in {"waiting_file", "needs_password", "ready"}
    ):
        await update.effective_message.reply_text("Читаю (без сохранения)…")
        if caption:
            prev_note = temp.get("note")
            temp["note"] = f"{prev_note}\n{caption}".strip() if prev_note else caption
        analyzed = await analyze_bytes(
            conn=conn,
            data_root=settings.assistant_data_dir,
            router=router,
            raw=raw,
            original_name=original,
            mime=mime,
        )
        temp_session.mark_ready(
            bot_data,
            chat_id,
            name=analyzed.name,
            text=analyzed.text,
            path=analyzed.path,
            kind=analyzed.kind,
            image_data_url=analyzed.image_data_url,
            needs_password=analyzed.needs_password,
        )
        if analyzed.needs_password:
            await update.effective_message.reply_text(
                f"«{analyzed.name}» запаролен. «возможные пароли …» или «пароль: …».\n"
                "«забей» — отменить."
            )
            return
        if not analyzed.text and not analyzed.image_data_url:
            await update.effective_message.reply_text(
                f"«{analyzed.name}»: {analyzed.summary}\n«забей» — закрыть."
            )
            return
        # If caption is a question, answer it; else describe readiness
        if caption and len(caption) > 2 and classify_intent(caption).kind not in {
            "ingest_start",
            "temp_read_start",
        }:
            await update.effective_message.reply_text(analyzed.summary)
            await _answer_temp_file(update, context, caption)
        else:
            await update.effective_message.reply_text(analyzed.summary)
            await _reply_temp_ready(update, context)
        return

    # --- library ingest ---
    if not session:
        await update.effective_message.reply_text(
            "Сейчас не принимаю файлы в хранилище.\n"
            "• Сохранить: «сейчас скину файлы, сохрани»\n"
            "• Только прочитать: «скину файл, не сохраняй»\n"
            "• Или ответь (reply) на сообщение с файлом вопросом."
        )
        return

    comment = file_store.take_pending_comment(conn, int(session["id"]))
    if caption:
        comment = f"{comment}\n{caption}".strip() if comment else caption

    file_id, save_msg = await save_telegram_bytes(
        conn=conn,
        data_root=settings.assistant_data_dir,
        raw=raw,
        original_name=original,
        mime=mime,
        category=session["category"] or "general",
        comment=comment,
        session_id=int(session["id"]),
    )
    index_msg = index_file(conn, settings.assistant_data_dir, file_id)
    # also vision-index images into ocr_text? skip for now — index_file handles docs
    conn.commit()

    note = f"\nКомментарий: {comment}" if comment else ""
    await update.effective_message.reply_text(
        f"{save_msg}\n{index_msg}{note}\n"
        "Можно ещё файл или комментарий. «готово» — закрыть приём. «забей» — отмена."
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

    if data.startswith("rem:"):
        await _on_reminder_action(query, context, data)
        return

    if data.startswith("cal:"):
        await _on_calendar(query, context, data)
        return

    if data.startswith("ctl:"):
        action = data.split(":", 1)[1]
        if action == "pause":
            repo.set_paused(conn, True, "manual")
            conn.commit()
            await query.edit_message_text(
                "На паузе.",
                reply_markup=resume_keyboard(),
            )
            return
        if action == "resume":
            repo.set_paused(conn, False)
            conn.commit()
            await query.edit_message_text(
                "Снова на связи.",
                reply_markup=home_keyboard(paused=False),
            )
            return
        if action == "status":
            lm: LMStudioClient = context.application.bot_data["lm"]
            paused = repo.is_paused(conn)
            await query.edit_message_text(
                status_html(
                    paused=paused,
                    reason=repo.get_state(conn, "pause_reason", ""),
                    lm_ok=await lm.healthcheck(),
                    model=settings.lm_studio_model,
                    n_people=len(repo.list_people(conn)),
                    n_bd=len(repo.list_birthdays(conn)),
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=home_keyboard(paused=paused),
            )
            return

    if data.startswith("menu:"):
        section = data.split(":", 1)[1]
        if section == "home":
            paused = repo.is_paused(conn)
            await query.edit_message_text(
                "На паузе. Нажми «Снять паузу»." if paused else "Что открыть?",
                reply_markup=home_keyboard(paused=paused),
            )
            return
        if section == "people":
            today = today_in_tz(settings.timezone)
            people = repo.list_people_with_birthdays(conn)
            await query.edit_message_text(
                people_list_html(people, today),
                parse_mode=ParseMode.HTML,
                reply_markup=people_keyboard(people, today),
            )
            return
        await query.edit_message_text(
            menu_section_html(section),
            parse_mode=ParseMode.HTML,
            reply_markup=section_keyboard(section),
        )
        return

    if data.startswith("p:view:"):
        person_id = int(data.split(":")[2])
        person = repo.get_person(conn, person_id)
        if not person:
            await query.edit_message_text("Не нашёл.")
            return
        bd = repo.get_birthday_for_person(conn, person_id)
        attrs = [
            {
                "key": a["key"],
                "label": a["label"],
                "value": a["value"],
            }
            for a in repo.list_person_attributes(conn, person_id)
        ]
        card = {
            "display_name": person["display_name"],
            "relation": person["relation"],
            "month": bd["month"] if bd else None,
            "day": bd["day"] if bd else None,
            "year": bd["year"] if bd else None,
        }
        today = today_in_tz(settings.timezone)
        await query.edit_message_text(
            person_card_html(card, attrs, today),
            parse_mode=ParseMode.HTML,
            reply_markup=person_keyboard(
                person_id,
                int(bd["month"]) if bd else None,
                int(bd["day"]) if bd else None,
                today.year,
            ),
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


async def _on_reminder_action(
    query, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    parts = data.split(":")
    # rem:s:one_shot:12:60  or rem:d:one_shot:12
    if len(parts) < 4:
        return
    op, kind, rid_s = parts[1], parts[2], parts[3]
    rid = int(rid_s)
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz=tz)

    if op == "d":
        if kind == "one_shot":
            repo.mark_one_shot_done(conn, rid)
            conn.commit()
        await query.edit_message_text("готово")
        return

    if op == "s" and len(parts) >= 5:
        minutes = int(parts[4])
        until = now + timedelta(minutes=minutes)
        if kind == "one_shot":
            repo.snooze_one_shot(conn, rid, until.isoformat())
            conn.commit()
        elif kind == "recurring":
            repo.bump_recurring_next(conn, rid, until.isoformat())
            conn.commit()
        await query.edit_message_text(f"отложено до {until.strftime('%d.%m %H:%M')}")


async def _on_calendar(query, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    today = today_in_tz(settings.timezone)

    if data == "cal:today":
        text, kb = month_payload(conn, settings, today.year, today.month)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "cal:week":
        agenda = week_agenda(conn, today, settings.timezone, 7)
        await query.edit_message_text(
            week_html(agenda),
            parse_mode=ParseMode.HTML,
            reply_markup=week_keyboard(agenda),
        )
        return

    if data.startswith("cal:m:"):
        raw = data[6:]
        year_s, month_s = raw.split("-", 1)
        year, month = int(year_s), int(month_s)
        text, kb = month_payload(conn, settings, year, month)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("cal:add:"):
        iso = data[8:]
        context.user_data["add_on_date"] = iso
        await query.edit_message_text(
            f"Что напомнить на {iso}?\nНапиши одним сообщением."
        )
        return

    if data.startswith("cal:snooze:"):
        day = date.fromisoformat(data[11:])
        events = events_for_day(conn, day, settings.timezone)
        await query.edit_message_text(
            f"Отложить · {day.strftime('%d.%m.%Y')}",
            reply_markup=snooze_pick_keyboard(day, events),
        )
        return

    if data.startswith("cal:d:"):
        day = date.fromisoformat(data[6:])
        events = events_for_day(conn, day, settings.timezone)
        await query.edit_message_text(
            day_detail_html(day, events),
            parse_mode=ParseMode.HTML,
            reply_markup=day_keyboard(day, events),
        )


def create_app(settings: Settings) -> Application:
    ensure_data_layout(settings.assistant_data_dir)
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    repo.ensure_runtime_schema(conn)
    lm = LMStudioClient(settings.lm_studio_base_url, settings.lm_studio_model)
    router = ModelRouter(
        lm,
        chat_model=settings.lm_studio_model,
        vision_model=settings.lm_studio_vision_model or None,
        transcribe_model=settings.lm_studio_transcribe_model or None,
    )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = conn
    application.bot_data["lm"] = lm
    application.bot_data["router"] = router

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("calendar", cmd_calendar))
    application.add_handler(CommandHandler("soon", cmd_soon))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(filters.VOICE, on_voice))
    application.add_handler(MessageHandler(filters.AUDIO, on_audio))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    return application


async def _post_init(application: Application) -> None:
    if application.job_queue:
        application.job_queue.run_repeating(
            process_due_reminders, interval=30, first=5, name="due_reminders"
        )


async def cmd_soon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    if not _is_owner(update, settings):
        return
    conn = context.application.bot_data["db"]
    today = today_in_tz(settings.timezone)
    agenda = week_agenda(conn, today, settings.timezone, 7)
    await update.effective_message.reply_text(
        week_html(agenda),
        parse_mode=ParseMode.HTML,
        reply_markup=week_keyboard(agenda),
    )


def run_bot(settings: Settings | None = None) -> None:
    import threading

    from app.config import load_settings
    from app.web.panel import run_web

    settings = settings or load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    web_port = getattr(settings, "web_port", 8765)
    t = threading.Thread(
        target=run_web,
        kwargs={"settings": settings, "host": "127.0.0.1", "port": web_port},
        daemon=True,
        name="wr-web",
    )
    t.start()
    log.info("Web panel http://127.0.0.1:%s", web_port)

    app = create_app(settings)
    log.info("Bot starting; data dir=%s", settings.assistant_data_dir)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
