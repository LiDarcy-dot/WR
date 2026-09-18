from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.db import repo
from app.reminders.rrule_utils import next_occurrence

log = logging.getLogger(__name__)


def quiet_ping_keyboard(reminder_kind: str, reminder_id: int) -> InlineKeyboardMarkup:
    # rem:s:{kind}:{id}:{minutes}  rem:d:{kind}:{id}
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "+1ч", callback_data=f"rem:s:{reminder_kind}:{reminder_id}:60"
                ),
                InlineKeyboardButton(
                    "+3ч", callback_data=f"rem:s:{reminder_kind}:{reminder_id}:180"
                ),
                InlineKeyboardButton(
                    "готово", callback_data=f"rem:d:{reminder_kind}:{reminder_id}"
                ),
            ]
        ]
    )


async def process_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: quiet short pushes, no LLM."""
    settings = context.application.bot_data["settings"]
    conn = context.application.bot_data["db"]
    if repo.is_paused(conn):
        return

    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz=tz)
    now_iso = now.isoformat()

    for row in repo.due_one_shots(conn, now_iso):
        title = row["title"]
        try:
            await context.bot.send_message(
                chat_id=settings.telegram_owner_id,
                text=f"• {title}",
                reply_markup=quiet_ping_keyboard("one_shot", int(row["id"])),
            )
            repo.mark_one_shot_sent(conn, int(row["id"]))
            conn.execute(
                """
                INSERT INTO reminder_events (
                    reminder_kind, reminder_id, planned_at, sent_at
                ) VALUES ('one_shot', ?, ?, datetime('now'))
                """,
                (int(row["id"]), row["fire_at"]),
            )
            conn.commit()
        except Exception:
            log.exception("failed quiet ping one_shot id=%s", row["id"])
            conn.rollback()

    for row in repo.due_recurring(conn, now_iso):
        title = row["title"]
        try:
            await context.bot.send_message(
                chat_id=settings.telegram_owner_id,
                text=f"• {title}",
                reply_markup=quiet_ping_keyboard("recurring", int(row["id"])),
            )
            try:
                nxt = next_occurrence(
                    row["rrule"],
                    row["dtstart"],
                    after=now,
                    timezone=row["timezone"] or settings.timezone,
                )
                repo.bump_recurring_next(conn, int(row["id"]), nxt.isoformat())
            except Exception:
                repo.bump_recurring_next(
                    conn, int(row["id"]), (now + timedelta(days=1)).isoformat()
                )
            conn.execute(
                """
                INSERT INTO reminder_events (
                    reminder_kind, reminder_id, planned_at, sent_at
                ) VALUES ('recurring', ?, ?, datetime('now'))
                """,
                (int(row["id"]), row["next_fire_at"]),
            )
            conn.commit()
        except Exception:
            log.exception("failed quiet ping recurring id=%s", row["id"])
            conn.rollback()
