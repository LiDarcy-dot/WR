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

WEB_HINTS = (
    "найди в инет",
    "найди в интернет",
    "погугли",
    "погугл",
    "поиск в сети",
    "поищи в сети",
    "поищи в интернет",
    "загугли",
    "что сейчас купить",
    "что лучше купить",
    "сравни цены",
    "актуальн",
    "в москве купить",
    "с доставкой",
    "самовывоз",
    "топ-",
    "топ 3",
    "топ3",
    "look up",
    "search the web",
    "google ",
)


@dataclass
class Intent:
    kind: str  # confirm | cancel | list_birthdays | recent_writes | web_search | chat
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

    if any(h in low for h in WEB_HINTS) or low.startswith("найди ") or low.startswith(
        "поищи "
    ):
        # avoid treating DB asks as web
        if not (
            "день рождения" in low
            or "дни рождения" in low
            or "в базе" in low
            or "что ты записал" in low
        ):
            return Intent("web_search", t)

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
