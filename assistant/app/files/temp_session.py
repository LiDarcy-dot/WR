from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from app.files.extract import extract_text_pages, pages_to_chunks
from app.files import store as file_store

log = logging.getLogger(__name__)

# Keep ephemeral sessions on the Application.bot_data["temp_read"] dict.
# Shape: chat_id -> {status, name, text, note, path?, needs_password?}


TEMP_SYSTEM = """Ты помощник по временному файлу пользователя.
Файл НЕ сохранён в постоянное хранилище — только в этой сессии.
Отвечай по-русски, опирайся ТОЛЬКО на текст файла ниже.
Если данных мало — скажи чего не хватает.
Если пользователь просил описать, КАК будешь отвечать — сначала кратко опиши подход, потом жди вопросы.
Указывай страницу, если она есть в фрагментах.
"""


def get_map(bot_data: dict) -> dict:
    if "temp_read" not in bot_data:
        bot_data["temp_read"] = {}
    return bot_data["temp_read"]


def get_session(bot_data: dict, chat_id: int) -> dict | None:
    return get_map(bot_data).get(int(chat_id))


def clear_session(bot_data: dict, chat_id: int) -> None:
    sess = get_map(bot_data).pop(int(chat_id), None)
    if not sess:
        return
    path = sess.get("path")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            Path(path).parent.rmdir()
        except Exception:  # noqa: BLE001
            pass


def start_waiting(bot_data: dict, chat_id: int, *, note: str | None = None) -> None:
    clear_session(bot_data, chat_id)
    get_map(bot_data)[int(chat_id)] = {
        "status": "waiting_file",
        "note": (note or "").strip()[:1500] or None,
        "name": None,
        "text": None,
        "path": None,
        "needs_password": False,
    }


def mark_ready(
    bot_data: dict,
    chat_id: int,
    *,
    name: str,
    text: str,
    path: str | None = None,
    needs_password: bool = False,
) -> None:
    sess = get_session(bot_data, chat_id) or {}
    note = sess.get("note")
    clear_session(bot_data, chat_id)
    get_map(bot_data)[int(chat_id)] = {
        "status": "ready" if text and not needs_password else (
            "needs_password" if needs_password else "ready"
        ),
        "note": note,
        "name": name,
        "text": text,
        "path": path,
        "needs_password": needs_password,
    }


def build_temp_context(sess: dict, question: str, *, max_chars: int = 12000) -> str:
    name = sess.get("name") or "файл"
    note = sess.get("note")
    body = (sess.get("text") or "")[:max_chars]
    lines = [f"Временный файл: {name}", ""]
    if note:
        lines.append(f"Инструкция пользователя к сессии: {note}")
        lines.append("")
    lines.append("Текст файла:")
    lines.append(body)
    lines.append("")
    lines.append(f"Вопрос / просьба пользователя: {question}")
    return "\n".join(lines)


def load_bytes_to_temp_text(
    conn,
    data_root: Path,
    raw: bytes,
    original_name: str,
) -> tuple[str, str | None, str | None]:
    """
    Write to a temp path under data_root/tmp_read, extract text.
    Returns (text, error, abs_path).
    error == 'password' if locked.
    """
    folder = data_root / "tmp_read"
    folder.mkdir(parents=True, exist_ok=True)
    safe = file_store.safe_filename(original_name)
    path = Path(tempfile.mkdtemp(prefix="tr_", dir=str(folder))) / safe
    path.write_bytes(raw)

    pages, err = extract_text_pages(path, password=None)
    if err == "password":
        for pwd in file_store.list_password_candidates(conn):
            pages, err = extract_text_pages(path, password=pwd)
            if err != "password":
                break
    if err == "password":
        return "", "password", str(path)
    if err:
        return "", err, str(path)
    if not pages:
        return "", "empty", str(path)

    chunks = pages_to_chunks(pages, max_chars=2000)
    parts = []
    for page, _idx, text in chunks:
        label = f"[стр. {page}] " if page else ""
        parts.append(label + text)
    return "\n\n".join(parts), None, str(path)


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
