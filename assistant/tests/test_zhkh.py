from __future__ import annotations

from datetime import date
from pathlib import Path

from app.actions.apply import apply_action
from app.db import connect, init_db
from app.db import repo
from app.intent import classify_intent
from app.zhkh.mosenergosbyt import (
    ensure_mosenergosbyt_setup,
    window_status,
)
from app.zhkh.parse import parse_zhkh_reading
from app.zhkh.service import (
    format_zhkh_status_html,
    get_submission,
    mark_submitted,
    record_reading,
)


def test_window_15_26() -> None:
    assert window_status(date(2026, 9, 14)).open is False
    assert window_status(date(2026, 9, 15)).open is True
    assert window_status(date(2026, 9, 26)).open is True
    assert window_status(date(2026, 9, 27)).open is False
    assert window_status(date(2026, 9, 20)).period == "2026-09"


def test_parse_reading() -> None:
    p = parse_zhkh_reading("показания 12345")
    assert p is not None and p.value == 12345.0
    p2 = parse_zhkh_reading("мосэнерго т1 100 т2 200")
    assert p2 is not None and p2.value == 100.0 and p2.t2 == 200.0
    assert parse_zhkh_reading("привет как дела") is None


def test_intents() -> None:
    assert classify_intent("жкх").kind == "list_zhkh"
    assert classify_intent("показания 999").kind == "zhkh_reading"
    assert classify_intent("подал показания").kind == "zhkh_mark_sent"


def test_seed_and_record(tmp_path: Path) -> None:
    db = tmp_path / "z.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.ensure_runtime_schema(conn)
    setup = ensure_mosenergosbyt_setup(conn, meter_number="14195368")
    assert setup["meter_number"] == "14195368"
    row = conn.execute(
        "SELECT meter_number, active FROM zhkh_meters WHERE id = ?",
        (setup["meter_id"],),
    ).fetchone()
    assert row["meter_number"] == "14195368"
    assert row["active"] == 1
    rem = conn.execute(
        "SELECT title FROM reminders_recurring WHERE source_type = 'zhkh_meter'"
    ).fetchone()
    assert rem and "14195368" in rem["title"]

    result = record_reading(conn, value=5555.0, period="2026-09", timezone="Europe/Moscow")
    assert result["status"] == "recorded"
    sub = get_submission(conn, result["meter_id"], "2026-09")
    assert sub["value"] == 5555.0

    marked = mark_submitted(conn, period="2026-09")
    assert marked["status"] == "submitted"

    html = format_zhkh_status_html(conn, timezone="Europe/Moscow")
    assert "14195368" in html
    assert "Мосэнергосбыт" in html


def test_apply_zhkh_actions(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.ensure_runtime_schema(conn)
    ensure_mosenergosbyt_setup(conn)
    msg = apply_action(
        conn,
        "record_zhkh_reading",
        {"value": 111.0, "meter_number": "14195368", "period": "2026-10"},
    )
    assert "111" in msg
    msg2 = apply_action(
        conn,
        "mark_zhkh_submitted",
        {"meter_number": "14195368", "period": "2026-10"},
    )
    assert "кабинет" in msg2.lower() or "подач" in msg2.lower()
