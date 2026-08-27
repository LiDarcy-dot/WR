from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u0400-\u04FF]+")


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = SAFE_NAME_RE.sub("_", base).strip("._")
    return (cleaned or "file")[:120]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_files_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingest_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            category TEXT NOT NULL DEFAULT 'general',
            title TEXT,
            pending_comment TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relative_path TEXT NOT NULL,
            original_name TEXT,
            mime TEXT,
            sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'inbox',
            source_type TEXT,
            source_id INTEGER,
            ocr_text TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS file_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            page INTEGER,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS file_secrets (
            file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
            password TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    # additive columns for older DBs
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)").fetchall()}
    alters = {
        "category": "TEXT",
        "comment": "TEXT",
        "title": "TEXT",
        "session_id": "INTEGER",
        "page_count": "INTEGER",
        "indexed_at": "TEXT",
        "needs_password": "INTEGER NOT NULL DEFAULT 0",
        "error": "TEXT",
    }
    for name, typ in alters.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE files ADD COLUMN {name} {typ}")

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts
        USING fts5(text, content='file_chunks', content_rowid='id')
        """
    )
    conn.commit()


def open_ingest_session(
    conn: sqlite3.Connection,
    chat_id: int,
    *,
    category: str = "general",
    title: str | None = None,
) -> int:
    # close previous open sessions for chat
    conn.execute(
        """
        UPDATE ingest_sessions
        SET status = 'closed', closed_at = datetime('now')
        WHERE chat_id = ? AND status = 'open'
        """,
        (chat_id,),
    )
    cur = conn.execute(
        """
        INSERT INTO ingest_sessions (chat_id, category, title)
        VALUES (?, ?, ?)
        """,
        (chat_id, category, title),
    )
    return int(cur.lastrowid)


def get_open_ingest(
    conn: sqlite3.Connection, chat_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM ingest_sessions
        WHERE chat_id = ? AND status = 'open'
        ORDER BY id DESC LIMIT 1
        """,
        (chat_id,),
    ).fetchone()


def set_pending_comment(
    conn: sqlite3.Connection, session_id: int, comment: str
) -> None:
    conn.execute(
        """
        UPDATE ingest_sessions
        SET pending_comment = ?
        WHERE id = ?
        """,
        (comment, session_id),
    )


def take_pending_comment(conn: sqlite3.Connection, session_id: int) -> str | None:
    row = conn.execute(
        "SELECT pending_comment FROM ingest_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not row or not row["pending_comment"]:
        return None
    comment = row["pending_comment"]
    conn.execute(
        "UPDATE ingest_sessions SET pending_comment = NULL WHERE id = ?",
        (session_id,),
    )
    return comment


def close_ingest_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        """
        UPDATE ingest_sessions
        SET status = 'closed', closed_at = datetime('now'), pending_comment = NULL
        WHERE id = ?
        """,
        (session_id,),
    )


def insert_file(
    conn: sqlite3.Connection,
    *,
    relative_path: str,
    original_name: str,
    mime: str | None,
    sha256: str,
    category: str,
    comment: str | None,
    session_id: int | None,
    title: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO files (
            relative_path, original_name, mime, sha256, status,
            category, comment, session_id, title
        ) VALUES (?, ?, ?, ?, 'stored', ?, ?, ?, ?)
        """,
        (
            relative_path,
            original_name,
            mime,
            sha256,
            category,
            comment,
            session_id,
            title or original_name,
        ),
    )
    return int(cur.lastrowid)


def find_file_by_sha(
    conn: sqlite3.Connection, sha256: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM files WHERE sha256 = ? ORDER BY id DESC LIMIT 1",
        (sha256,),
    ).fetchone()


def list_files(
    conn: sqlite3.Connection,
    *,
    category: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    if category:
        return list(
            conn.execute(
                """
                SELECT * FROM files
                WHERE status = 'stored' AND category = ?
                ORDER BY id DESC LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        )
    return list(
        conn.execute(
            """
            SELECT * FROM files
            WHERE status = 'stored'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    )


def get_file(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()


def latest_needs_password(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM files
        WHERE needs_password = 1
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()


def set_file_password(conn: sqlite3.Connection, file_id: int, password: str) -> None:
    conn.execute(
        """
        INSERT INTO file_secrets (file_id, password, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(file_id) DO UPDATE SET
            password = excluded.password,
            updated_at = datetime('now')
        """,
        (file_id, password),
    )
    conn.execute(
        "UPDATE files SET needs_password = 0, error = NULL WHERE id = ?",
        (file_id,),
    )


def get_file_password(conn: sqlite3.Connection, file_id: int) -> str | None:
    row = conn.execute(
        "SELECT password FROM file_secrets WHERE file_id = ?",
        (file_id,),
    ).fetchone()
    return row["password"] if row else None


def replace_chunks(
    conn: sqlite3.Connection,
    file_id: int,
    chunks: list[tuple[int | None, int, str]],
) -> None:
    old = conn.execute(
        "SELECT id FROM file_chunks WHERE file_id = ?", (file_id,)
    ).fetchall()
    for r in old:
        conn.execute("DELETE FROM file_chunks_fts WHERE rowid = ?", (r["id"],))
    conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
    for page, idx, text in chunks:
        cur = conn.execute(
            """
            INSERT INTO file_chunks (file_id, page, chunk_index, text)
            VALUES (?, ?, ?, ?)
            """,
            (file_id, page, idx, text),
        )
        conn.execute(
            "INSERT INTO file_chunks_fts(rowid, text) VALUES (?, ?)",
            (int(cur.lastrowid), text),
        )
    conn.execute(
        """
        UPDATE files
        SET indexed_at = datetime('now'),
            page_count = ?,
            updated_at = datetime('now'),
            status = 'stored',
            error = NULL
        WHERE id = ?
        """,
        (max((c[0] or 0) for c in chunks) if chunks else 0, file_id),
    )


def mark_file_needs_password(conn: sqlite3.Connection, file_id: int, err: str) -> None:
    conn.execute(
        """
        UPDATE files
        SET needs_password = 1, error = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (err[:500], file_id),
    )


def mark_file_error(conn: sqlite3.Connection, file_id: int, err: str) -> None:
    conn.execute(
        """
        UPDATE files
        SET error = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (err[:500], file_id),
    )


def search_chunks(
    conn: sqlite3.Connection, query: str, limit: int = 12
) -> list[sqlite3.Row]:
    tokens = re.findall(r"[\w\u0400-\u04FF]+", query)
    # drop ultra-common Russian glue words for FTS
    stop = {
        "как",
        "что",
        "это",
        "для",
        "или",
        "при",
        "по",
        "на",
        "в",
        "и",
        "а",
        "the",
        "a",
        "to",
        "of",
        "in",
        "on",
        "and",
    }
    meaningful = [t for t in tokens if t.lower() not in stop and len(t) > 1]
    if not meaningful:
        meaningful = tokens
    if not meaningful:
        return []

    def _run(match_q: str) -> list[sqlite3.Row]:
        try:
            return list(
                conn.execute(
                    """
                    SELECT c.id, c.file_id, c.page, c.text,
                           f.original_name, f.title, f.category, f.relative_path
                    FROM file_chunks_fts fts
                    JOIN file_chunks c ON c.id = fts.rowid
                    JOIN files f ON f.id = c.file_id
                    WHERE file_chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (match_q, limit),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            return []

    rows = _run(" ".join(meaningful))
    if len(rows) < 3 and len(meaningful) > 1:
        rows = _run(" OR ".join(meaningful))
    if rows:
        return rows

    # fallback LIKE on strongest token
    like_token = max(meaningful, key=len)
    like = f"%{like_token[:80]}%"
    return list(
        conn.execute(
            """
            SELECT c.id, c.file_id, c.page, c.text,
                   f.original_name, f.title, f.category, f.relative_path
            FROM file_chunks c
            JOIN files f ON f.id = c.file_id
            WHERE c.text LIKE ?
            ORDER BY c.id DESC
            LIMIT ?
            """,
            (like, limit),
        ).fetchall()
    )


def category_slug(text: str) -> str:
    low = text.lower()
    mapping = (
        ("мануал", "manuals"),
        ("manual", "manuals"),
        ("кт", "ct_manuals"),
        ("ct ", "ct_manuals"),
        ("жкх", "zhkh"),
        ("отчет", "reports"),
        ("отчёт", "reports"),
    )
    for key, slug in mapping:
        if key in low:
            return slug
    slug = SAFE_NAME_RE.sub("_", text.strip().lower())[:40].strip("_")
    return slug or "general"
