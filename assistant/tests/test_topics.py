from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.topics.classify import classify_topic, format_hello_html
from app.topics.store import (
    due_hello_deletions,
    ensure_topics_schema,
    mark_hello_deleted,
    record_hello_message,
    upsert_topic,
)
from app.update.versioning import is_newer, read_local_version
from pathlib import Path


def test_classify_english_and_russian() -> None:
    assert classify_topic("Inbox").mode == "inbox"
    assert classify_topic("Documents & manuals").mode == "docs"
    assert classify_topic("Family / People").mode == "people"
    assert classify_topic("Reminders").mode == "life"
    assert classify_topic("AI chat").mode == "chat"
    assert classify_topic("System").mode == "system"
    assert classify_topic("ЖКХ").mode == "home"
    assert classify_topic("General", is_general=True).mode == "general"
    custom = classify_topic("Project Phoenix")
    assert custom.mode == "custom"
    assert "Phoenix" in custom.summary_ru


def test_hello_html_mentions_ttl() -> None:
    u = classify_topic("Docs")
    html = format_hello_html(u, is_new=True)
    assert "Новая тема" in html
    assert "24 часа" in html
    assert "docs" in html


def test_topic_hello_deletion_queue(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ensure_topics_schema(conn)
    upsert_topic(
        conn,
        chat_id=-100,
        thread_id=3,
        title="Inbox",
        mode="inbox",
        created_by=1,
    )
    # force past due
    conn.execute(
        """
        INSERT INTO topic_hello_messages (chat_id, thread_id, message_id, delete_at)
        VALUES (?, ?, ?, ?)
        """,
        (-100, 3, 42, "2000-01-01T00:00:00"),
    )
    conn.commit()
    due = due_hello_deletions(conn, now=datetime.now(timezone.utc))
    assert len(due) == 1
    mark_hello_deleted(conn, int(due[0]["id"]))
    conn.commit()
    assert due_hello_deletions(conn) == []


def test_future_hello_not_due(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "t2.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ensure_topics_schema(conn)
    record_hello_message(
        conn, chat_id=-100, thread_id=1, message_id=7, ttl_hours=24
    )
    conn.commit()
    assert due_hello_deletions(conn) == []
    # rewind delete_at
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
    conn.execute(
        "UPDATE topic_hello_messages SET delete_at = ?",
        (past.isoformat(timespec="seconds"),),
    )
    conn.commit()
    assert len(due_hello_deletions(conn)) == 1


def test_version_1009() -> None:
    root = Path(__file__).resolve().parents[1]
    assert read_local_version(root) == "1.014"
    assert is_newer("1.014", "1.013")
