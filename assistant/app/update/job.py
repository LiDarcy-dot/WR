from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from telegram.ext import ContextTypes

from app.update.apply import (
    apply_update,
    check_for_update,
    consume_result,
    hard_restart,
    probe_versions,
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


def _as_context(application) -> ContextTypes.DEFAULT_TYPE:
    """Minimal context for fallback updater when JobQueue is missing."""
    return SimpleNamespace(application=application, bot=application.bot)  # type: ignore[return-value]


async def report_startup_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Call once after bot is up: report update result + local/remote versions."""
    settings = context.application.bot_data["settings"]
    install_root = context.application.bot_data["install_root"]
    local = read_local_version(install_root)
    result = consume_result(install_root)

    log.info(
        "updater startup: version=%s auto=%s interval=%ss root=%s",
        local,
        settings.auto_update,
        settings.auto_update_interval_sec,
        install_root,
    )

    if result:
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

    info = await probe_versions(
        install_root,
        repo=settings.auto_update_repo,
        branch=settings.auto_update_branch,
    )
    context.application.bot_data["last_version_check"] = {
        "local": info.local,
        "remote": info.remote,
        "newer": info.newer,
        "error": info.error,
    }

    if info.error:
        await notify_owner(
            context,
            f"⚠️ Не смог сверить версию с GitHub.\n"
            f"Локально: {format_version(local)}\n"
            f"Ошибка: {info.error}\n"
            f"Автообновление: "
            f"{'вкл' if settings.auto_update else 'выкл'}.",
        )
    else:
        au = (
            f"Автообновление каждые {settings.auto_update_interval_sec}с."
            if settings.auto_update
            else "Автообновление выключено (AUTO_UPDATE=0)."
        )
        line = (
            f"Ассистент на связи. Версия {format_version(info.local)}. "
            f"В репо: {format_version(info.remote)}. {au}"
        )
        if not context.application.bot_data.get("announce_version_once"):
            context.application.bot_data["announce_version_once"] = True
            await notify_owner(context, line)
        elif info.newer:
            await notify_owner(context, line)

        if info.newer and settings.auto_update:
            await notify_owner(
                context,
                "🔄 При старте вижу более новую версию — обновляюсь…\n"
                f"{format_version(info.local)} → {format_version(info.remote)}",
            )
            await _apply_and_restart(context, info.local, info.remote)


async def run_update_now(context: ContextTypes.DEFAULT_TYPE, *, force_notify: bool = True) -> str:
    """Manual/panel-triggered update check. Returns status text."""
    settings = context.application.bot_data["settings"]
    install_root = context.application.bot_data["install_root"]
    info = await probe_versions(
        install_root,
        repo=settings.auto_update_repo,
        branch=settings.auto_update_branch,
    )
    context.application.bot_data["last_version_check"] = {
        "local": info.local,
        "remote": info.remote,
        "newer": info.newer,
        "error": info.error,
    }
    if info.error:
        msg = (
            f"⚠️ Проверка обновлений не вышла.\n"
            f"Локально: {format_version(info.local)}\n"
            f"Ошибка: {info.error}"
        )
        if force_notify:
            await notify_owner(context, msg)
        return msg

    if not info.newer:
        msg = (
            f"Актуальная версия.\n"
            f"Локально: {format_version(info.local)}\n"
            f"В репо: {format_version(info.remote)}"
        )
        if force_notify:
            await notify_owner(context, msg)
        return msg

    await notify_owner(
        context,
        "🔄 Нашёл новую версию.\n"
        f"{format_version(info.local)} → {format_version(info.remote)}\n"
        "Делаю бэкап и обновляюсь…",
    )
    await _apply_and_restart(context, info.local, info.remote)
    return f"Обновление {format_version(info.local)} → {format_version(info.remote)}"


async def _apply_and_restart(
    context: ContextTypes.DEFAULT_TYPE, local: str, remote: str
) -> None:
    settings = context.application.bot_data["settings"]
    install_root = context.application.bot_data["install_root"]
    from app.update.apply import UpdatePlan

    plan = UpdatePlan(
        local=local,
        remote=remote,
        branch=settings.auto_update_branch,
        repo=settings.auto_update_repo,
    )
    outcome = await asyncio.to_thread(
        apply_update,
        install_root,
        plan,
        backups_root=settings.backups_dir,
    )
    if not outcome.ok:
        await notify_owner(
            context,
            "❌ Обновление сорвалось.\n"
            f"{outcome.message}\n"
            f"Recovery: {'восстановил бэкап' if outcome.restored else 'не удалось'}\n"
            f"Бэкап: {outcome.backup_dir or '—'}",
        )
        return

    await notify_owner(
        context,
        "📦 Файлы обновлены. Через ~5 сек убью старый процесс и "
        "открою новое окно бота…\n"
        f"{outcome.message}\n"
        f"Бэкап: {outcome.backup_dir}\n"
        "Если через ~20 сек не отвечу — закрой окна и запусти "
        "UPDATE.cmd (двойной клик) или блок из UPDATE_NOW.txt.",
    )
    # schedule helper first, then hard-kill self (never await application.stop)
    hard_restart(install_root, delay_sec=5)


async def process_auto_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    if not settings.auto_update:
        return
    if _update_lock.locked():
        return

    async with _update_lock:
        try:
            plan = await check_for_update(
                context.application.bot_data["install_root"],
                repo=settings.auto_update_repo,
                branch=settings.auto_update_branch,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("version check failed: %s", exc)
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
            log.info("auto_update: already current")
            return

        await notify_owner(
            context,
            "🔄 Нашёл новую версию.\n"
            f"{format_version(plan.local)} → {format_version(plan.remote)}\n"
            "Делаю бэкап и обновляюсь без вопросов…",
        )
        await _apply_and_restart(context, plan.local, plan.remote)


async def fallback_updater_loop(application) -> None:
    """Used when JobQueue / APScheduler is unavailable."""
    log.warning("Starting fallback asyncio updater (no JobQueue)")
    ctx = _as_context(application)
    try:
        await asyncio.sleep(8)
        await report_startup_update(ctx)
    except Exception:
        log.exception("fallback startup update failed")
    settings = application.bot_data["settings"]
    while True:
        try:
            await asyncio.sleep(max(30, int(settings.auto_update_interval_sec)))
            if settings.auto_update:
                await process_auto_update(ctx)
        except Exception:
            log.exception("fallback auto_update tick failed")
