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
from app.files.ingest import index_file, save_telegram_bytes
from app.files.query import DOCS_SYSTEM, build_docs_context, list_files_html
from app.files.store import category_slug, search_chunks
from app.intent import classify_intent
from app.llm.lm_studio import LMStudioClient, WEB_SYSTEM
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

    if intent.kind == "cancel":
        if pending:
            await cancel_pending(update, context, pending)
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

    # --- file library ---
    open_session = file_store.get_open_ingest(conn, chat_id)

    if intent.kind == "ingest_start":
        cat = category_slug(text)
        sid = file_store.open_ingest_session(
            conn, chat_id, category=cat, title=text[:200]
        )
        conn.commit()
        await update.effective_message.reply_text(
            "Ок, жду файлы.\n"
            f"Папка: <code>{cat}</code>\n"
            "Можно писать комментарии между файлами.\n"
            "Когда закончишь — «готово» или «всё».",
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
        "web_search",
        "list_birthdays",
        "ask_docs",
        "list_files",
        "file_password",
        "ingest_start",
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
    file_id, password = _parse_file_password(text)
    if not password:
        await update.effective_message.reply_text(
            "Формат: <code>пароль к файлу 12: secret</code>\n"
            "или для последнего запароленного: <code>пароль: secret</code>",
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
    msg = index_file(conn, settings.assistant_data_dir, file_id)
    conn.commit()
    name = row["original_name"] or f"id={file_id}"
    await update.effective_message.reply_text(f"{name}: {msg}")


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
    session = file_store.get_open_ingest(conn, chat_id)
    if not session:
        await update.effective_message.reply_text(
            "Сейчас не принимаю файлы в хранилище.\n"
            "Скажи сначала: «сейчас скину файлы, сохрани» — и пришли снова."
        )
        return

    msg = update.effective_message
    caption = (msg.caption or "").strip() or None
    comment = file_store.take_pending_comment(conn, int(session["id"]))
    if caption:
        comment = f"{comment}\n{caption}".strip() if comment else caption

    try:
        if kind == "document" and msg.document:
            tg_file = await msg.document.get_file()
            original = msg.document.file_name or f"doc_{msg.document.file_unique_id}"
            mime = msg.document.mime_type
            raw = bytes(await tg_file.download_as_bytearray())
        elif kind == "photo" and msg.photo:
            photo = msg.photo[-1]
            tg_file = await photo.get_file()
            original = f"photo_{photo.file_unique_id}.jpg"
            mime = "image/jpeg"
            raw = bytes(await tg_file.download_as_bytearray())
        else:
            await update.effective_message.reply_text("Не понял вложение.")
            return
    except Exception as exc:  # noqa: BLE001
        log.exception("telegram download failed")
        await update.effective_message.reply_text(f"Не скачал файл: {exc}")
        return

    if len(raw) > 45 * 1024 * 1024:
        await update.effective_message.reply_text("Слишком большой файл (>45 МБ).")
        return

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
    conn.commit()

    note = f"\nКомментарий: {comment}" if comment else ""
    await update.effective_message.reply_text(
        f"{save_msg}\n{index_msg}{note}\n"
        "Можно ещё файл или комментарий. «готово» — закрыть приём."
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

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = conn
    application.bot_data["lm"] = lm

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
