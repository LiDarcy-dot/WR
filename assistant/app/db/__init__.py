from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.schema import DEFAULT_JOBS, DEFAULT_PERSONA_PROMPT, SCHEMA_SQL


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        existing = conn.execute(
            "SELECT COUNT(*) AS c FROM persona_presets"
        ).fetchone()["c"]
        if existing == 0:
            conn.execute(
                """
                INSERT INTO persona_presets (name, system_prompt, is_active)
                VALUES (?, ?, 1)
                """,
                ("default", DEFAULT_PERSONA_PROMPT),
            )
        for name, priority, interval in DEFAULT_JOBS:
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs (name, priority, interval_seconds, enabled)
                VALUES (?, ?, ?, 1)
                """,
                (name, priority, interval),
            )
        for key, value in (
            ("paused", "0"),
            ("pause_reason", ""),
            ("model_loaded", "0"),
            ("vpn_ok", "unknown"),
        ):
            conn.execute(
                """
                INSERT OR IGNORE INTO assistant_state (key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )
        conn.commit()
