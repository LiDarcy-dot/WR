from __future__ import annotations

import json
from pathlib import Path

from app.actions.apply import apply_action, format_action_card
from app.db import connect, init_db
from app.db import repo
from app.llm.lm_studio import parse_model_content
from app.reminders.rrule_utils import humanize_recurrence, next_occurrence
from app.storage_layout import ensure_data_layout


def test_data_layout_and_db(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_data_layout(root)
    assert (root / "db").is_dir()
    assert (root / "inbox").is_dir()
    db = root / "db" / "assistant.sqlite3"
    init_db(db)
    conn = connect(db)
    assert repo.get_active_persona(conn)
    assert repo.get_state(conn, "paused") == "0"


def test_person_birthday_wishlist(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite3"
    init_db(db)
    conn = connect(db)
    pid = repo.upsert_person_with_birthday_and_attrs(
        conn,
        "Ваня",
        relation="друг",
        month=1,
        day=1,
        year=1998,
        attributes=[
            {
                "key": "wishlist_url",
                "label": "Вишлист",
                "value": "https://example.com/wish",
                "value_type": "url",
            }
        ],
    )
    conn.commit()
    row = conn.execute(
        "SELECT display_name FROM people WHERE id = ?", (pid,)
    ).fetchone()
    assert row["display_name"] == "Ваня"
    bd = conn.execute(
        "SELECT year, month, day FROM birthdays WHERE person_id = ?", (pid,)
    ).fetchone()
    assert (bd["year"], bd["month"], bd["day"]) == (1998, 1, 1)
    attr = conn.execute(
        "SELECT value FROM person_attributes WHERE person_id = ? AND key = ?",
        (pid, "wishlist_url"),
    ).fetchone()
    assert "example.com" in attr["value"]


def test_rrule_next() -> None:
    text = humanize_recurrence(
        "FREQ=MONTHLY;INTERVAL=2;BYDAY=3MO",
        "2026-04-01",
        "10:00",
    )
    assert "FREQ=MONTHLY" in text
    nxt = next_occurrence(
        "FREQ=MONTHLY;INTERVAL=2;BYDAY=3MO",
        "2026-04-01T00:00:00+03:00",
        after=__import__("datetime").datetime(2026, 4, 1, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Moscow")),
    )
    assert nxt.month in (4, 6, 8, 10, 12)


def test_apply_recurring_and_entity(tmp_path: Path) -> None:
    db = tmp_path / "b.sqlite3"
    init_db(db)
    conn = connect(db)
    msg = apply_action(
        conn,
        "create_reminder_recurring",
        {
            "title": "тест",
            "rrule": "FREQ=WEEKLY;BYDAY=MO",
            "dtstart": "2026-04-06",
            "time_of_day": "09:00",
            "timezone": "Europe/Moscow",
        },
        timezone="Europe/Moscow",
    )
    assert "регулярное" in msg
    msg2 = apply_action(
        conn,
        "create_entity_type",
        {
            "name": "subscriptions",
            "title": "Подписки",
            "fields": [
                {"key": "price", "label": "Цена", "field_type": "number"},
                {"key": "pay_day", "label": "День оплаты", "field_type": "number"},
            ],
        },
    )
    assert "тип сущности" in msg2


def test_parse_model_json_and_fallback() -> None:
    reply = parse_model_content(
        json.dumps(
            {
                "mode": "propose_action",
                "message": "Сохранить?",
                "action_type": "upsert_person",
                "payload": {"display_name": "Ваня"},
            },
            ensure_ascii=False,
        )
    )
    assert reply.mode == "propose_action"
    assert reply.payload["display_name"] == "Ваня"
    reply2 = parse_model_content("Просто текст без json")
    assert reply2.mode == "chat"
    card = format_action_card(
        "upsert_person",
        {
            "display_name": "Ваня",
            "birthday_day": 1,
            "birthday_month": 1,
            "birthday_year": 1998,
            "attributes": [{"key": "wishlist_url", "label": "Вишлист", "value": "x"}],
        },
    )
    assert "Ваня" in card
    assert "Вишлист" in card


def test_strip_think_then_json() -> None:
    raw = (
        "<think>долго думаю</think>\n"
        '{"mode":"chat","message":"Привет","action_type":null,"payload":{}}'
    )
    reply = parse_model_content(raw)
    assert reply.mode == "chat"
    assert reply.message == "Привет"


def test_intent_confirm_and_birthdays() -> None:
    from app.intent import classify_intent

    assert classify_intent("Да").kind == "confirm"
    assert classify_intent("+").kind == "confirm"
    assert classify_intent("ок").kind == "confirm"
    assert classify_intent("нет").kind == "cancel"
    assert (
        classify_intent(
            "напиши все дни рождения в порядке от ближайшего к дальнему"
        ).kind
        == "list_birthdays"
    )
    assert (
        classify_intent("покажи что ты записал за сегодня в базы данных").kind
        == "recent_writes"
    )


def test_calendar_month_marks(tmp_path: Path) -> None:
    from app.calendar_view import events_for_month, month_grid

    db = tmp_path / "cal.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.upsert_person_with_birthday_and_attrs(
        conn, "Папа", relation="папа", month=5, day=25, year=1970
    )
    conn.commit()
    ev = events_for_month(conn, 2026, 5)
    assert 25 in ev
    assert any(x.kind == "birthday" for x in ev[25])
    grid = month_grid(2026, 5)
    assert grid[0]  # has weeks
    assert any(25 in week for week in grid)


def test_birthday_order_and_memory(tmp_path: Path) -> None:
    from datetime import date

    from app.memory.formatters import days_until_next_birthday

    today = date(2026, 8, 27)
    assert days_until_next_birthday(8, 28, today) == 1
    assert days_until_next_birthday(5, 25, today) > 1

    db = tmp_path / "m.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.upsert_person_with_birthday_and_attrs(
        conn, "Папа", relation="папа", month=5, day=25, year=1970
    )
    repo.upsert_person_with_birthday_and_attrs(
        conn, "Серга", relation="друг", month=8, day=28, year=1995
    )
    conn.commit()
    block = repo.build_memory_block(conn, "Europe/Moscow")
    assert "Папа" in block
    assert "Серга" in block
    assert "Дней рождения: 2" in block

