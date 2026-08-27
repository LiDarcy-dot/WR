from __future__ import annotations

import re
from dataclasses import dataclass


CONFIRM_RE = re.compile(
    r"^\s*(\+|✅|☑️|да+|угу|ага|ок|окей|okay|yes|yep|lf|дф|сохрани(ть)?|"
    r"подтверждаю|верно|правильно|го|согласен|хорошо|запиши|пиши)\s*[.!.]*\s*$",
    re.IGNORECASE,
)
CANCEL_RE = re.compile(
    r"^\s*(-|❌|нет|отмена|cancel|не надо|не надо|отменить)\s*[.!.]*\s*$",
    re.IGNORECASE,
)


@dataclass
class Intent:
    kind: str  # confirm | cancel | list_birthdays | recent_writes | chat
    raw: str


def classify_intent(text: str) -> Intent:
    t = (text or "").strip()
    if not t:
        return Intent("chat", t)
    if CONFIRM_RE.match(t):
        return Intent("confirm", t)
    if CANCEL_RE.match(t):
        return Intent("cancel", t)

    low = t.lower().replace("ё", "е")
    if any(
        x in low
        for x in (
            "дни рождения",
            "день рождения",
            "др ",
            " др",
            "birthdays",
            "кто когда родился",
            "ближайш",
        )
    ) and any(
        x in low
        for x in (
            "напиши",
            "покажи",
            "список",
            "все",
            "порядок",
            "какие",
            "кто",
            "перечисл",
            "выведи",
        )
    ):
        return Intent("list_birthdays", t)

    # softer: just "все дни рождения" / "дни рождения по порядку"
    if re.search(r"дн[ия] рожден", low) and any(
        x in low for x in ("все", "список", "порядок", "ближай", "покажи", "напиши")
    ):
        return Intent("list_birthdays", t)

    if any(
        x in low
        for x in (
            "что ты записал",
            "что записано",
            "за сегодня",
            "сегодня в баз",
            "что сохранил",
            "что сохранено",
            "покажи базу",
            "что в базе",
            "последние запис",
        )
    ):
        return Intent("recent_writes", t)

    return Intent("chat", t)
