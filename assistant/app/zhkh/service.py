from __future__ import annotations

import html
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.zhkh.mosenergosbyt import (
    CABINET_URL,
    DEFAULT_METER_NUMBER,
    PROVIDER,
    ensure_mosenergosbyt_setup,
    period_key,
    window_status,
)


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def get_active_meter(
    conn: sqlite3.Connection,
    *,
    meter_number: str | None = None,
) -> sqlite3.Row | None:
    ensure_mosenergosbyt_setup(conn, meter_number=meter_number or DEFAULT_METER_NUMBER)
    if meter_number:
        return conn.execute(
            """
            SELECT m.*, a.title AS account_title, a.provider, a.url
            FROM zhkh_meters m
            JOIN zhkh_accounts a ON a.id = m.account_id
            WHERE m.meter_number = ? AND m.active = 1
            ORDER BY m.id LIMIT 1
            """,
            (meter_number.strip(),),
        ).fetchone()
    return conn.execute(
        """
        SELECT m.*, a.title AS account_title, a.provider, a.url
        FROM zhkh_meters m
        JOIN zhkh_accounts a ON a.id = m.account_id
        WHERE a.provider = ? AND m.active = 1
        ORDER BY m.id LIMIT 1
        """,
        (PROVIDER,),
    ).fetchone()


def get_submission(
    conn: sqlite3.Connection, meter_id: int, period: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM zhkh_submissions
        WHERE meter_id = ? AND period = ?
        """,
        (meter_id, period),
    ).fetchone()


def record_reading(
    conn: sqlite3.Connection,
    *,
    value: float,
    period: str | None = None,
    meter_number: str | None = None,
    source: str = "telegram",
    timezone: str = "Europe/Moscow",
) -> dict:
    meter = get_active_meter(conn, meter_number=meter_number)
    if not meter:
        raise RuntimeError("Счётчик Мосэнергосбыт не найден")
    today = datetime.now(ZoneInfo(timezone)).date()
    period = period or period_key(today)
    note_src = source
    conn.execute(
        """
        INSERT INTO zhkh_submissions (meter_id, period, value, status, source, confirmed_at)
        VALUES (?, ?, ?, 'recorded', ?, datetime('now'))
        ON CONFLICT(meter_id, period) DO UPDATE SET
            value = excluded.value,
            status = 'recorded',
            source = excluded.source,
            confirmed_at = datetime('now'),
            updated_at = datetime('now')
        """,
        (int(meter["id"]), period, float(value), note_src),
    )
    conn.execute(
        """
        UPDATE zhkh_meters
        SET last_value = ?, last_submitted_at = datetime('now'),
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (float(value), int(meter["id"])),
    )
    conn.commit()
    return {
        "meter_id": int(meter["id"]),
        "meter_number": meter["meter_number"],
        "period": period,
        "value": float(value),
        "status": "recorded",
    }


def mark_submitted(
    conn: sqlite3.Connection,
    *,
    period: str | None = None,
    meter_number: str | None = None,
    timezone: str = "Europe/Moscow",
) -> dict:
    meter = get_active_meter(conn, meter_number=meter_number)
    if not meter:
        raise RuntimeError("Счётчик Мосэнергосбыт не найден")
    today = datetime.now(ZoneInfo(timezone)).date()
    period = period or period_key(today)
    row = get_submission(conn, int(meter["id"]), period)
    if not row:
        raise RuntimeError(
            f"Нет записанных показаний за {period}. Сначала напиши: показания <число>"
        )
    conn.execute(
        """
        UPDATE zhkh_submissions
        SET status = 'submitted',
            confirmed_at = datetime('now'),
            updated_at = datetime('now')
        WHERE meter_id = ? AND period = ?
        """,
        (int(meter["id"]), period),
    )
    conn.commit()
    return {
        "meter_id": int(meter["id"]),
        "meter_number": meter["meter_number"],
        "period": period,
        "value": row["value"],
        "status": "submitted",
    }


def format_zhkh_status_html(
    conn: sqlite3.Connection,
    *,
    timezone: str = "Europe/Moscow",
    meter_number: str | None = None,
) -> str:
    setup = ensure_mosenergosbyt_setup(
        conn, meter_number=meter_number or DEFAULT_METER_NUMBER, timezone=timezone
    )
    meter = get_active_meter(conn, meter_number=setup["meter_number"])
    win = window_status(timezone=timezone)
    sub = get_submission(conn, int(meter["id"]), win.period) if meter else None

    if win.open:
        win_line = f"🟢 {esc(win.label)}"
    elif win.today.day < 15:
        win_line = f"🟡 окно откроется {win.day_start}-го (до {win.day_end}-го)"
    else:
        win_line = f"⚪ {esc(win.label)}"

    if sub is None:
        sub_line = "показания за этот месяц: <b>ещё нет</b>"
    else:
        st = sub["status"]
        st_ru = {
            "recorded": "записаны у бота (в кабинет ещё не отмечено)",
            "submitted": "отмечены как поданные в кабинет",
            "drafted": "черновик",
        }.get(st, st)
        val = sub["value"]
        val_s = f"{val:g}" if val is not None else "—"
        sub_line = f"показания {esc(win.period)}: <b>{esc(val_s)}</b> · {esc(st_ru)}"

    last = meter["last_value"] if meter else None
    last_s = f"{last:g}" if last is not None else "—"

    tip = (
        "Напиши: <i>показания 12345</i> — сохраню.\n"
        "После ручной подачи в кабинете: <i>подал показания</i>.\n"
        "Автоподача в ЛК — позже (браузер-агент)."
    )
    if win.open and (sub is None or sub["status"] != "submitted"):
        tip = (
            "Сейчас можно передать в кабинете.\n"
            "1) Напиши боту число → сохраню\n"
            f"2) Внеси в <a href=\"{CABINET_URL}\">ЛК Мосэнергосбыт</a>\n"
            "3) Напиши: <i>подал показания</i>"
        )

    return (
        f"<b>ЖКХ · Мосэнергосбыт</b>\n"
        f"Счётчик: <code>{esc(meter['meter_number'] if meter else setup['meter_number'])}</code>\n"
        f"Оплачивается сейчас: только этот\n"
        f"Период: <code>{esc(win.period)}</code>\n"
        f"{win_line}\n"
        f"{sub_line}\n"
        f"Последнее известное: {esc(last_s)} {esc(meter['unit'] if meter else 'кВт·ч')}\n"
        f"Кабинет: {esc(CABINET_URL)}\n\n"
        f"{tip}"
    )


def needs_window_nudge(
    conn: sqlite3.Connection,
    *,
    timezone: str = "Europe/Moscow",
) -> str | None:
    """If window open and not submitted — return short nudge text."""
    win = window_status(timezone=timezone)
    if not win.open:
        return None
    meter = get_active_meter(conn)
    if not meter:
        return None
    sub = get_submission(conn, int(meter["id"]), win.period)
    if sub and sub["status"] == "submitted":
        return None
    if sub and sub["status"] == "recorded":
        if win.today.day >= 24:
            return (
                f"Показания {sub['value']:g} записаны у бота, "
                f"но в кабинет ещё не отмечены. Окно до {win.day_end}-го."
            )
        return None
    # no reading yet — nudge on 15, 20, 24, 26
    if win.today.day in {15, 20, 24, 25, 26}:
        return (
            f"Окно Мосэнергосбыт открыто (до {win.day_end}-го). "
            f"Счётчик {meter['meter_number']}: напиши «показания <число>»."
        )
    return None
