from __future__ import annotations

from typing import Any


def _store(bot_data: dict) -> dict:
    return bot_data.setdefault("zhkh_photo_sessions", {})


def get_session(bot_data: dict, chat_id: int) -> dict | None:
    return _store(bot_data).get(int(chat_id))


def start_session(bot_data: dict, chat_id: int) -> dict:
    sess = {
        "t1": None,
        "t2": None,
        "t3": None,
        "hints": [],
    }
    _store(bot_data)[int(chat_id)] = sess
    return sess


def clear_session(bot_data: dict, chat_id: int) -> None:
    _store(bot_data).pop(int(chat_id), None)


def merge_reading(
    sess: dict,
    *,
    t1: float | None,
    t2: float | None,
    t3: float | None,
    force_slot: str | None = None,
) -> dict:
    """Merge vision result into session. force_slot overrides which field a single value fills."""
    if force_slot == "t1" and t1 is None and t2 is not None and t3 is None:
        t1, t2 = t2, None
    if force_slot == "t2" and t2 is None and t1 is not None and t3 is None:
        t2, t1 = t1, None
    if force_slot == "t3" and t3 is None and t1 is not None and t2 is None:
        t3, t1 = t1, None

    if force_slot == "t1" and t1 is not None:
        sess["t1"] = t1
    elif force_slot == "t2" and t2 is not None:
        sess["t2"] = t2
    elif force_slot == "t3" and t3 is not None:
        sess["t3"] = t3
    else:
        if t1 is not None:
            sess["t1"] = t1
        if t2 is not None:
            sess["t2"] = t2
        if t3 is not None:
            sess["t3"] = t3
    return sess


def ready_for_confirm(sess: dict) -> bool:
    return sess.get("t1") is not None and sess.get("t2") is not None


def missing_label(sess: dict) -> str:
    miss = []
    if sess.get("t1") is None:
        miss.append("T1 (день)")
    if sess.get("t2") is None:
        miss.append("T2 (ночь)")
    return ", ".join(miss)


def creds_wait_store(bot_data: dict) -> dict:
    return bot_data.setdefault("zhkh_awaiting_creds", {})


def set_awaiting_creds(
    bot_data: dict,
    chat_id: int,
    *,
    purpose: str = "check",
    submit: dict[str, Any] | None = None,
    partial_login: str | None = None,
) -> None:
    """purpose: check | submit. Always a structured envelope."""
    # back-compat: if someone passes old flat submit payload as sole arg via misuse — ignore
    env: dict[str, Any] = {
        "purpose": purpose if purpose in {"check", "submit"} else "check",
        "submit": submit,
        "partial_login": partial_login,
    }
    creds_wait_store(bot_data)[int(chat_id)] = env


def pop_awaiting_creds(bot_data: dict, chat_id: int) -> dict | None:
    return creds_wait_store(bot_data).pop(int(chat_id), None)


def get_awaiting_creds(bot_data: dict, chat_id: int) -> dict | None:
    raw = creds_wait_store(bot_data).get(int(chat_id))
    if not raw:
        return None
    # migrate old flat submit payload {t1,t2,...}
    if "purpose" not in raw and ("t1" in raw or "meter_number" in raw):
        return {"purpose": "submit", "submit": raw, "partial_login": None}
    return raw
