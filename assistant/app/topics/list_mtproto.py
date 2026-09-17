from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Public credentials from Telegram Android client (overridable via .env).
_DEFAULT_API_ID = 6
_DEFAULT_API_HASH = "eb06d4abfb49dc3eeb1aeb98ae0f581e"


async def list_forum_topics_mtproto(
    *,
    bot_token: str,
    chat_id: int,
    api_id: int | None = None,
    api_hash: str | None = None,
) -> list[dict[str, Any]]:
    """Try to list forum topics via Telethon (MTProto).

    Bot API cannot enumerate topics. If Telegram rejects the call for bots,
    raises RuntimeError — caller should use learn-mode fallback.
    """
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.messages import GetForumTopicsRequest
        from telethon.tl.types import ForumTopic as TlForumTopic
        from telethon.tl.types import ForumTopicDeleted
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("telethon не установлен") from exc

    api_id = int(api_id or _DEFAULT_API_ID)
    api_hash = (api_hash or _DEFAULT_API_HASH).strip()
    out: list[dict[str, Any]] = []

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.start(bot_token=bot_token)
        peer = await client.get_input_entity(chat_id)
        offset_topic = 0
        offset_id = 0
        offset_date = None
        seen: set[int] = set()
        for _ in range(20):
            result = await client(
                GetForumTopicsRequest(
                    peer=peer,
                    offset_date=offset_date,
                    offset_id=offset_id or 0,
                    offset_topic=offset_topic or 0,
                    limit=100,
                )
            )
            topics = list(getattr(result, "topics", []) or [])
            if not topics:
                break
            for t in topics:
                if isinstance(t, ForumTopicDeleted):
                    continue
                if not isinstance(t, TlForumTopic):
                    # duck-type
                    tid = int(getattr(t, "id", 0) or 0)
                    title = str(getattr(t, "title", "") or "")
                else:
                    tid = int(t.id)
                    title = str(t.title or "")
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                out.append(
                    {
                        "thread_id": tid,
                        "title": title or f"topic-{tid}",
                        "is_general": tid == 1,
                    }
                )
            last = topics[-1]
            offset_topic = int(getattr(last, "id", 0) or 0)
            # pagination fields from accompanying messages if present
            msgs = list(getattr(result, "messages", []) or [])
            if msgs:
                m = msgs[-1]
                offset_id = int(getattr(m, "id", 0) or 0)
                offset_date = getattr(m, "date", None)
            if len(topics) < 50:
                break
        if not any(x["thread_id"] == 1 for x in out):
            out.insert(
                0,
                {"thread_id": 1, "title": "General", "is_general": True},
            )
        return out
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
