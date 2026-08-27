from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app.files.extract import extract_text_pages, pages_to_chunks
from app.files import store as file_store

log = logging.getLogger(__name__)

# bot_data["temp_read"][chat_id] =
# {status, name, text, note, path, kind, image_data_url?, needs_password?}


TEMP_SYSTEM = """Ты помощник по временному вложению пользователя.
Вложение НЕ сохранено в постоянное хранилище — только в этой сессии.
Отвечай по-русски, опирайся на переданный текст/распознавание.
Если данных мало — скажи чего не хватает.
Указывай страницу, если она есть.
"""


def get_map(bot_data: dict) -> dict:
    if "temp_read" not in bot_data:
        bot_data["temp_read"] = {}
    return bot_data["temp_read"]


def get_session(bot_data: dict, chat_id: int) -> dict | None:
    return get_map(bot_data).get(int(chat_id))


def _unlink_path(path: str | None) -> None:
    if not path:
        return
    try:
        p = Path(path)
        p.unlink(missing_ok=True)
        try:
            p.parent.rmdir()
        except Exception:
            pass
    except Exception:  # noqa: BLE001
        pass


def clear_session(bot_data: dict, chat_id: int) -> None:
    sess = get_map(bot_data).pop(int(chat_id), None)
    if not sess:
        return
    _unlink_path(sess.get("path"))


def start_waiting(bot_data: dict, chat_id: int, *, note: str | None = None) -> None:
    clear_session(bot_data, chat_id)
    get_map(bot_data)[int(chat_id)] = {
        "status": "waiting_file",
        "note": (note or "").strip()[:1500] or None,
        "name": None,
        "text": None,
        "path": None,
        "kind": None,
        "image_data_url": None,
        "needs_password": False,
    }


def mark_ready(
    bot_data: dict,
    chat_id: int,
    *,
    name: str,
    text: str,
    path: str | None = None,
    kind: str = "text",
    image_data_url: str | None = None,
    needs_password: bool = False,
) -> None:
    sess = get_session(bot_data, chat_id) or {}
    note = sess.get("note")
    old_path = sess.get("path")
    # drop session entry without deleting the NEW path
    get_map(bot_data).pop(int(chat_id), None)
    if old_path and old_path != path:
        _unlink_path(old_path)

    status = "needs_password" if needs_password else "ready"
    get_map(bot_data)[int(chat_id)] = {
        "status": status,
        "note": note,
        "name": name,
        "text": text or "",
        "path": path,
        "kind": kind,
        "image_data_url": image_data_url,
        "needs_password": needs_password,
    }


def build_temp_context(sess: dict, question: str, *, max_chars: int = 12000) -> str:
    name = sess.get("name") or "файл"
    note = sess.get("note")
    kind = sess.get("kind") or "text"
    body = (sess.get("text") or "")[:max_chars]
    lines = [f"Временное вложение: {name} (тип: {kind})", ""]
    if note:
        lines.append(f"Инструкция пользователя к сессии: {note}")
        lines.append("")
    if body:
        lines.append("Распознанное / текст:")
        lines.append(body)
        lines.append("")
    else:
        lines.append("(текста пока нет — опирайся на то, что известно о файле)")
        lines.append("")
    lines.append(f"Вопрос / просьба пользователя: {question}")
    return "\n".join(lines)


def save_raw_temp(
    data_root: Path, raw: bytes, original_name: str
) -> str:
    folder = data_root / "tmp_read"
    folder.mkdir(parents=True, exist_ok=True)
    safe = file_store.safe_filename(original_name)
    path = Path(tempfile.mkdtemp(prefix="tr_", dir=str(folder))) / safe
    path.write_bytes(raw)
    return str(path)


def load_bytes_to_temp_text(
    conn,
    data_root: Path,
    raw: bytes,
    original_name: str,
) -> tuple[str, str | None, str | None]:
    """
    Write to a temp path under data_root/tmp_read, extract text from docs.
    Returns (text, error, abs_path).
    error == 'password' | 'empty' | other.
    """
    path = save_raw_temp(data_root, raw, original_name)
    pages, err = extract_text_pages(Path(path), password=None)
    if err == "password":
        for pwd in file_store.list_password_candidates(conn):
            pages, err = extract_text_pages(Path(path), password=pwd)
            if err != "password":
                break
    if err == "password":
        return "", "password", path
    if err:
        return "", err, path
    if not pages:
        return "", "empty", path

    chunks = pages_to_chunks(pages, max_chars=2000)
    parts = []
    for page, _idx, text in chunks:
        label = f"[стр. {page}] " if page else ""
        parts.append(label + text)
    return "\n\n".join(parts), None, path


def unlock_temp_path(path: str, password: str) -> tuple[str, str | None]:
    pages, err = extract_text_pages(Path(path), password=password)
    if err == "password":
        return "", "password"
    if err:
        return "", err
    if not pages:
        return "", "empty"
    chunks = pages_to_chunks(pages, max_chars=2000)
    parts = []
    for page, _idx, text in chunks:
        label = f"[стр. {page}] " if page else ""
        parts.append(label + text)
    return "\n\n".join(parts), None
