from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

PROVIDER = "mosenergosbyt"
CABINET_URL = "https://my.mosenergosbyt.ru/"
DEFAULT_METER_NUMBER = "14195368"
SUBMIT_DAY_START = 15
SUBMIT_DAY_END = 26
KIND = "electricity"
UNIT = "кВт·ч"
ACCOUNT_TITLE = "Мосэнергосбыт"


@dataclass(frozen=True)
class WindowStatus:
    today: date
    period: str
    open: bool
    day_start: int = SUBMIT_DAY_START
    day_end: int = SUBMIT_DAY_END

    @property
    def label(self) -> str:
        if self.open:
            left = self.day_end - self.today.day
            if left <= 0:
                return "окно открыто · последний день"
            if left == 1:
                return "окно открыто · остался 1 день"
            return f"окно открыто · осталось {left} дн."
        if self.today.day < self.day_start:
            return f"окно ещё закрыто · откроется {self.day_start}-го"
        return f"окно закрыто (было {self.day_start}–{self.day_end})"


def period_key(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.year:04d}-{d.month:02d}"


def window_status(today: date | None = None, *, timezone: str = "Europe/Moscow") -> WindowStatus:
    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    open_ = SUBMIT_DAY_START <= today.day <= SUBMIT_DAY_END
    return WindowStatus(today=today, period=period_key(today), open=open_)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def ensure_zhkh_columns(conn: sqlite3.Connection) -> None:
    cols = _column_names(conn, "zhkh_meters")
    if "meter_number" not in cols:
        conn.execute("ALTER TABLE zhkh_meters ADD COLUMN meter_number TEXT")


def ensure_mosenergosbyt_setup(
    conn: sqlite3.Connection,
    *,
    meter_number: str = DEFAULT_METER_NUMBER,
    timezone: str = "Europe/Moscow",
) -> dict:
    """Idempotent: account + active electricity meter + monthly reminder on the 15th."""
    ensure_zhkh_columns(conn)
    meter_number = (meter_number or DEFAULT_METER_NUMBER).strip()

    acc = conn.execute(
        """
        SELECT id FROM zhkh_accounts
        WHERE provider = ? AND active = 1
        ORDER BY id LIMIT 1
        """,
        (PROVIDER,),
    ).fetchone()
    if acc:
        account_id = int(acc["id"])
        conn.execute(
            """
            UPDATE zhkh_accounts
            SET title = ?, url = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (ACCOUNT_TITLE, CABINET_URL, account_id),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO zhkh_accounts (title, provider, account_number, url, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (ACCOUNT_TITLE, PROVIDER, None, CABINET_URL),
        )
        account_id = int(cur.lastrowid)

    meter = conn.execute(
        """
        SELECT id FROM zhkh_meters
        WHERE account_id = ? AND meter_number = ?
        ORDER BY id LIMIT 1
        """,
        (account_id, meter_number),
    ).fetchone()
    if meter:
        meter_id = int(meter["id"])
        conn.execute(
            """
            UPDATE zhkh_meters
            SET kind = ?, unit = ?, submit_rule = ?, active = 1,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (KIND, UNIT, f"{SUBMIT_DAY_START}-{SUBMIT_DAY_END}", meter_id),
        )
    else:
        # Deactivate other meters on this account — user pays only this one for now
        conn.execute(
            """
            UPDATE zhkh_meters
            SET active = 0, updated_at = datetime('now')
            WHERE account_id = ? AND (meter_number IS NULL OR meter_number != ?)
            """,
            (account_id, meter_number),
        )
        cur = conn.execute(
            """
            INSERT INTO zhkh_meters (
                account_id, kind, unit, submit_rule, meter_number, active
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                account_id,
                KIND,
                UNIT,
                f"{SUBMIT_DAY_START}-{SUBMIT_DAY_END}",
                meter_number,
            ),
        )
        meter_id = int(cur.lastrowid)

    # Monthly ping on the 15th (window open)
    reminder_title = f"Показания Мосэнергосбыт · счётчик {meter_number}"
    existing = conn.execute(
        """
        SELECT id FROM reminders_recurring
        WHERE source_type = 'zhkh_meter' AND source_id = ? AND status = 'active'
        LIMIT 1
        """,
        (meter_id,),
    ).fetchone()
    if not existing:
        from app.reminders.rrule_utils import next_occurrence

        today = datetime.now(ZoneInfo(timezone)).date()
        dtstart = f"{today.year:04d}-{today.month:02d}-15"
        rrule = "FREQ=MONTHLY;BYMONTHDAY=15"
        nxt = next_occurrence(
            rrule,
            f"{dtstart}T00:00:00+03:00",
            timezone=timezone,
        )
        conn.execute(
            """
            INSERT INTO reminders_recurring (
                title, body, rrule, dtstart, time_of_day, timezone,
                next_fire_at, status, source_type, source_id
            ) VALUES (?, ?, ?, ?, '10:00', ?, ?, 'active', 'zhkh_meter', ?)
            """,
            (
                reminder_title,
                (
                    f"Окно передачи {SUBMIT_DAY_START}–{SUBMIT_DAY_END}. "
                    f"Напиши боту: показания <число>. Кабинет: {CABINET_URL}"
                ),
                rrule,
                dtstart,
                timezone,
                nxt.isoformat(),
                meter_id,
            ),
        )

    conn.commit()
    return {
        "account_id": account_id,
        "meter_id": meter_id,
        "meter_number": meter_number,
        "provider": PROVIDER,
    }
