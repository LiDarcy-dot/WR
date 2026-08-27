from __future__ import annotations

import logging
from pathlib import Path

from app.files import store
from app.files.extract import extract_text_pages, pages_to_chunks

log = logging.getLogger(__name__)


async def save_telegram_bytes(
    *,
    conn,
    data_root: Path,
    raw: bytes,
    original_name: str,
    mime: str | None,
    category: str,
    comment: str | None,
    session_id: int | None,
) -> tuple[int, str]:
    """Save file to disk + DB. Returns (file_id, status_message)."""
    digest = store.sha256_bytes(raw)
    existing = store.find_file_by_sha(conn, digest)
    if existing and existing["status"] == "stored":
        # still allow new comment link? keep duplicate reference note
        return int(existing["id"]), f"уже был: {existing['original_name']} (id={existing['id']})"

    safe = store.safe_filename(original_name)
    folder = data_root / "documents" / category
    folder.mkdir(parents=True, exist_ok=True)
    rel = Path("documents") / category / f"{digest[:10]}_{safe}"
    abs_path = data_root / rel
    abs_path.write_bytes(raw)

    file_id = store.insert_file(
        conn,
        relative_path=str(rel).replace("\\", "/"),
        original_name=original_name,
        mime=mime,
        sha256=digest,
        category=category,
        comment=comment,
        session_id=session_id,
        title=original_name,
    )
    return file_id, f"сохранён: {original_name} (id={file_id})"


def index_file(conn, data_root: Path, file_id: int) -> str:
    row = store.get_file(conn, file_id)
    if not row:
        return "файл не найден"
    path = data_root / row["relative_path"]
    if not path.exists():
        store.mark_file_error(conn, file_id, "file missing on disk")
        return "файл пропал с диска"

    password = store.get_file_password(conn, file_id)
    pages, err = extract_text_pages(path, password=password)
    if err == "password":
        store.mark_file_needs_password(conn, file_id, "нужен пароль")
        return "нужен пароль к файлу"
    if err:
        store.mark_file_error(conn, file_id, err)
        return f"не разобрал: {err}"
    if not pages:
        store.mark_file_error(conn, file_id, "нет текста (возможно скан/картинка)")
        return "сохранил, но текста нет (скан/картинка — OCR позже)"

    chunks = pages_to_chunks(pages)
    store.replace_chunks(conn, file_id, chunks)
    return f"проиндексирован: {len(pages)} стр., {len(chunks)} фрагм."
