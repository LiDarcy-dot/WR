from __future__ import annotations

import asyncio
import logging

from telegram.ext import ContextTypes

from app.update.apply import (
    apply_update,
    check_for_update,
    consume_result,
    schedule_restart,
)
from app.update.versioning import format_version, read_local_version

log = logging.getLogger(__name__)

_update_lock = asyncio.Lock()


async def notify_owner(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    settings = context.application.bot_data["settings"]
    try:
        await context.bot.send_message(
            chat_id=settings.telegram_owner_id,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notify failed: %s", exc)


async def report_startup_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Call once after bot is up: report previous update attempt result."""
    settings = context.application.bot_data["settings"]
    install_root = context.application.bot_data["install_root"]
    local = read_local_version(install_root)
    result = consume_result(install_root)
    if not result:
        # quiet hello with version on first start after enabling updater
        if context.application.bot_data.get("announce_version_once"):
            return
        context.application.bot_data["announce_version_once"] = True
        await notify_owner(
            context,
            f"Ассистент на связи. Версия {format_version(local)}. "
            f"Автообновление каждые {settings.auto_update_interval_sec}с.",
        )
        return

    if result.get("ok"):
        await notify_owner(
            context,
            "✅ Обновление завершено.\n"
            f"{format_version(str(result.get('from')))} → "
            f"{format_version(str(result.get('to')))}\n"
            f"Бэкап: {result.get('backup_dir') or '—'}",
        )
    else:
        restored = "да" if result.get("restored") else "нет"
        await notify_owner(
            context,
            "❌ Обновление не удалось.\n"
            f"Целились на {format_version(str(result.get('to')))}, "
            f"сейчас {format_version(local)}.\n"
            f"Recovery из бэкапа: {restored}\n"
            f"{result.get('error') or result.get('message') or ''}".strip(),
        )


async def process_auto_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    if not settings.auto_update:
        return
    install_root = context.application.bot_data["install_root"]
    if _update_lock.locked():
        return

    async with _update_lock:
        try:
            plan = await check_for_update(
                install_root,
                repo=settings.auto_update_repo,
                branch=settings.auto_update_branch,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("version check failed: %s", exc)
            # don't spam every 2 min — only log; optional soft notify once
            fail_key = "update_check_fail_notified"
            if not context.application.bot_data.get(fail_key):
                context.application.bot_data[fail_key] = True
                await notify_owner(
                    context,
                    f"⚠️ Не смог проверить обновления: {exc}",
                )
            return

        context.application.bot_data["update_check_fail_notified"] = False
        if not plan:
            return

        await notify_owner(
            context,
            "🔄 Нашёл новую версию.\n"
            f"{format_version(plan.local)} → {format_version(plan.remote)}\n"
            "Делаю бэкап и обновляюсь без вопросов…",
        )

        # apply is sync/blocking — run in thread
        outcome = await asyncio.to_thread(
            apply_update,
            install_root,
            plan,
            backups_root=settings.backups_dir,
        )

        if outcome.ok:
            await notify_owner(
                context,
                "📦 Файлы обновлены, перезапускаюсь…\n"
                f"{outcome.message}\n"
                f"Бэкап: {outcome.backup_dir}",
            )
            try:
                schedule_restart(install_root)
            except Exception as exc:  # noqa: BLE001
                await notify_owner(
                    context,
                    f"Код обновлён, но автоперезапуск не вышел: {exc}\n"
                    "Перезапусти START_BOT.bat вручную.",
                )
                return
            await asyncio.sleep(1.5)
            try:
                await context.application.stop()
            except Exception:
                pass
            try:
                await context.application.shutdown()
            except Exception:
                pass
            import os

            os._exit(0)
            return

        msg = (
            "❌ Обновление сорвалось.\n"
            f"{outcome.message}\n"
            f"Recovery: {'восстановил бэкап' if outcome.restored else 'не удалось восстановить'}\n"
            f"Бэкап: {outcome.backup_dir or '—'}"
        )
        await notify_owner(context, msg)


async def _stop_soon(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unused helper kept for clarity; restart path exits inline."""
    await asyncio.sleep(0)
