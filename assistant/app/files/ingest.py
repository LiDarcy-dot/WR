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

    pages, err, used_pwd = _extract_with_candidates(conn, path, file_id)
    if err == "password":
        n = len(store.list_password_candidates(conn))
        store.mark_file_needs_password(conn, file_id, "нужен пароль")
        if n:
            return (
                f"нужен пароль к файлу ({n} известных не подошли). "
                "Пришли ещё: «возможные пароли …»"
            )
        return "нужен пароль к файлу — напиши «возможные пароли …» или «пароль к файлу id: …»"
    if err:
        store.mark_file_error(conn, file_id, err)
        return f"не разобрал: {err}"

    # remember working password even if page text is empty (scans)
    if used_pwd:
        store.set_file_password(conn, file_id, used_pwd)
        store.add_password_candidates(conn, [used_pwd], source="unlocked")
    else:
        # opened without password — clear stale lock flag
        conn.execute(
            "UPDATE files SET needs_password = 0, error = NULL WHERE id = ?",
            (file_id,),
        )

    if not pages:
        store.mark_file_error(conn, file_id, "нет текста (возможно скан/картинка)")
        return "сохранил, но текста нет (скан/картинка — OCR позже)"

    chunks = pages_to_chunks(pages)
    store.replace_chunks(conn, file_id, chunks)
    hint = " (пароль подошёл)" if used_pwd else ""
    return f"проиндексирован: {len(pages)} стр., {len(chunks)} фрагм.{hint}"


def _extract_with_candidates(
    conn, path: Path, file_id: int
) -> tuple[list[tuple[int, str]], str | None, str | None]:
    """Try open PDF, then known file password, then candidate pool."""
    pages, err = extract_text_pages(path, password=None)
    if err != "password":
        return pages, err, None

    tried: set[str] = set()
    ordered: list[str] = []
    known = store.get_file_password(conn, file_id)
    if known:
        ordered.append(known)
    for cand in store.list_password_candidates(conn):
        if cand not in ordered:
            ordered.append(cand)

    for pwd in ordered:
        if pwd in tried:
            continue
        tried.add(pwd)
        pages, err = extract_text_pages(path, password=pwd)
        if err != "password":
            return pages, err, pwd
    return [], "password", None


def try_unlock_pending(conn, data_root: Path) -> list[str]:
    """Retry all files that still need a password. Returns status lines."""
    lines: list[str] = []
    for row in store.list_files_needing_password(conn):
        fid = int(row["id"])
        name = row["original_name"] or f"id={fid}"
        msg = index_file(conn, data_root, fid)
        lines.append(f"• {name} (id={fid}): {msg}")
    return lines
