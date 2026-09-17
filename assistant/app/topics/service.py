from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from app.topics.classify import TopicUnderstanding, classify_topic, format_hello_html
from app.topics import store as topic_store

if TYPE_CHECKING:
    from telegram import Bot

log = logging.getLogger(__name__)


async def send_topic_hello(
    bot: Bot,
    conn,
    *,
    chat_id: int,
    thread_id: int,
    understanding: TopicUnderstanding,
    is_new: bool,
    ttl_hours: int = 24,
) -> int | None:
    text = format_hello_html(understanding, is_new=is_new)
    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": ParseMode.HTML,
        "disable_notification": True,
    }
    if thread_id and thread_id > 0:
        kwargs["message_thread_id"] = thread_id
    try:
        msg = await bot.send_message(**kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "topic hello failed chat=%s thread=%s: %s", chat_id, thread_id, exc
        )
        return None
    topic_store.record_hello_message(
        conn,
        chat_id=chat_id,
        thread_id=thread_id,
        message_id=msg.message_id,
        ttl_hours=ttl_hours,
    )
    conn.commit()
    return int(msg.message_id)


async def register_and_greet(
    bot: Bot,
    conn,
    *,
    chat_id: int,
    thread_id: int,
    title: str,
    created_by: int | None,
    is_general: bool = False,
    is_new: bool = False,
    force: bool = False,
) -> TopicUnderstanding:
    u = classify_topic(title, is_general=is_general or thread_id == 1)
    existing = topic_store.get_topic(conn, chat_id, thread_id)
    topic_store.upsert_topic(
        conn,
        chat_id=chat_id,
        thread_id=thread_id,
        title=u.title_norm,
        mode=u.mode,
        created_by=created_by,
        is_general=u.mode == "general" or is_general,
    )
    conn.commit()
    # Avoid spamming if already greeted recently unless force/new
    if existing and not force and not is_new:
        return u
    await send_topic_hello(
        bot,
        conn,
        chat_id=chat_id,
        thread_id=thread_id,
        understanding=u,
        is_new=is_new,
    )
    return u


async def announce_topic_list(
    bot: Bot,
    conn,
    *,
    chat_id: int,
    topics: list[dict],
    created_by: int | None,
    force: bool = True,
) -> list[TopicUnderstanding]:
    results: list[TopicUnderstanding] = []
    for t in topics:
        thread_id = int(t["thread_id"])
        title = str(t.get("title") or f"topic-{thread_id}")
        is_general = bool(t.get("is_general")) or thread_id == 1
        u = await register_and_greet(
            bot,
            conn,
            chat_id=chat_id,
            thread_id=thread_id,
            title=title,
            created_by=created_by,
            is_general=is_general,
            is_new=False,
            force=force,
        )
        results.append(u)
    return results


async def process_due_topic_hello_deletions(context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = context.application.bot_data["db"]
    rows = topic_store.due_hello_deletions(conn)
    for row in rows:
        try:
            await context.bot.delete_message(
                chat_id=int(row["chat_id"]),
                message_id=int(row["message_id"]),
            )
        except Exception as exc:  # noqa: BLE001
            log.info(
                "delete hello msg %s/%s: %s",
                row["chat_id"],
                row["message_id"],
                exc,
            )
        topic_store.mark_hello_deleted(conn, int(row["id"]))
    if rows:
        conn.commit()


def is_forum_group(chat) -> bool:
    if chat is None:
        return False
    if chat.type not in (ChatType.SUPERGROUP, ChatType.GROUP):
        return False
    return bool(getattr(chat, "is_forum", False))


async def on_forum_topic_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    user = update.effective_user
    # Only react to owner's topic ops (or any create while bot is member — still ok)
    created = msg.forum_topic_created
    edited = msg.forum_topic_edited
    if not created and not edited:
        return
    thread_id = msg.message_thread_id or 0
    if not thread_id:
        return
    if created:
        title = created.name
        is_new = True
    else:
        assert edited is not None
        if not edited.name:
            return  # icon-only edit
        title = edited.name
        is_new = False
    conn = context.application.bot_data["db"]
    await register_and_greet(
        context.bot,
        conn,
        chat_id=chat.id,
        thread_id=thread_id,
        title=title,
        created_by=user.id if user else None,
        is_new=is_new,
        force=True,
    )
    from app.db import repo

    repo.set_state(conn, "assistant_group_id", str(chat.id))
    conn.commit()
    _ = settings


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scan forum topics and post understanding into each."""
    settings = context.application.bot_data["settings"]
    user = update.effective_user
    chat = update.effective_chat
    if not user or user.id != settings.telegram_owner_id:
        return
    if not chat:
        return

    conn = context.application.bot_data["db"]
    from app.db import repo

    target_chat_id = chat.id
    if chat.type == ChatType.PRIVATE:
        stored = repo.get_state(conn, "assistant_group_id", "")
        if not stored and settings.telegram_group_id:
            stored = str(settings.telegram_group_id)
        if not stored:
            await update.effective_message.reply_text(
                "Напиши /topics прямо в группе-форуме "
                "(или задай TELEGRAM_GROUP_ID в .env)."
            )
            return
        target_chat_id = int(stored)
        await update.effective_message.reply_text(
            f"Сканирую темы группы {target_chat_id}…"
        )
    else:
        if not is_forum_group(chat) and not getattr(chat, "is_forum", False):
            # still try — some clients omit is_forum on updates
            pass
        repo.set_state(conn, "assistant_group_id", str(chat.id))
        conn.commit()
        await update.effective_message.reply_text(
            "Сканирую темы форума…",
            message_thread_id=update.effective_message.message_thread_id,
        )

    topics: list[dict] = []
    err: str | None = None
    try:
        from app.topics.list_mtproto import list_forum_topics_mtproto

        topics = await list_forum_topics_mtproto(
            bot_token=settings.telegram_bot_token,
            chat_id=target_chat_id,
            api_id=settings.telegram_api_id or None,
            api_hash=settings.telegram_api_hash or None,
        )
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:300]
        log.warning("mtproto topic list failed: %s", exc)

    if not topics:
        # Fallback: General + anything already known in DB
        known = topic_store.list_topics(conn, target_chat_id)
        topics = [
            {
                "thread_id": int(r["thread_id"]),
                "title": r["title"],
                "is_general": bool(r["is_general"]),
            }
            for r in known
        ]
        if not any(t["thread_id"] == 1 for t in topics):
            topics.insert(
                0, {"thread_id": 1, "title": "General", "is_general": True}
            )
        # enable learn mode: greet unseen topics on first owner message
        repo.set_state(conn, "topics_learn_mode", "1")
        conn.commit()
        note = (
            "Полный список тем Bot API не отдаёт"
            + (f" ({err})" if err else "")
            + ".\n"
            "Поздароваюсь с General и уже известными темами.\n"
            "Открой остальные темы и напиши там что угодно — "
            "я сразу пришлю, как понял каждую (сообщение исчезнет через 24ч)."
        )
        try:
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=note,
                message_thread_id=1,
            )
        except Exception:
            if update.effective_message:
                await update.effective_message.reply_text(note)

    results = await announce_topic_list(
        context.bot,
        conn,
        chat_id=target_chat_id,
        topics=topics,
        created_by=user.id,
        force=True,
    )
    lines = [f"· {u.title_norm} → {u.label_ru} (`{u.mode}`)" for u in results]
    summary = "Готово. Темы:\n" + "\n".join(lines[:30])
    if len(lines) > 30:
        summary += f"\n… и ещё {len(lines) - 30}"
    try:
        await context.bot.send_message(
            chat_id=settings.telegram_owner_id,
            text=summary,
        )
    except Exception:
        pass


async def maybe_learn_topic_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """If learn-mode or unknown topic — greet once. Returns True if handled as learn."""
    settings = context.application.bot_data["settings"]
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return False
    if user.id != settings.telegram_owner_id:
        return False
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False
    thread_id = msg.message_thread_id
    if not thread_id:
        return False
    # ignore pure commands except we still may register
    conn = context.application.bot_data["db"]
    from app.db import repo

    existing = topic_store.get_topic(conn, chat.id, thread_id)
    learn = repo.get_state(conn, "topics_learn_mode", "0") == "1"
    if existing and not learn:
        return False
    if existing:
        return False

    title = f"topic-{thread_id}"
    # Try to get name from reply_to forum_topic_created if present
    if msg.reply_to_message and msg.reply_to_message.forum_topic_created:
        title = msg.reply_to_message.forum_topic_created.name
    elif msg.is_topic_message:
        # no title in update — keep placeholder; edited later on forum_topic_edited
        title = f"Topic {thread_id}"

    await register_and_greet(
        context.bot,
        conn,
        chat_id=chat.id,
        thread_id=thread_id,
        title=title,
        created_by=user.id,
        is_new=False,
        force=True,
    )
    repo.set_state(conn, "assistant_group_id", str(chat.id))
    conn.commit()
    return False  # don't swallow the user message — continue normal handling
