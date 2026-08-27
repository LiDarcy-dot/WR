from __future__ import annotations

import re
from dataclasses import dataclass


CONFIRM_RE = re.compile(
    r"^\s*(\+|✅|☑️|да+|угу|ага|ок|окей|okay|yes|yep|lf|дф|"
    r"подтверждаю|верно|правильно|го|согласен|хорошо)\s*[.!.]*\s*$",
    re.IGNORECASE,
)
CANCEL_RE = re.compile(
    r"^\s*(-|❌|нет|отмена|cancel|не надо|отменить)\s*[.!.]*\s*$",
    re.IGNORECASE,
)

# Abort active file/temp session (broader than cancel-of-card)
ABORT_PHRASES = (
    "забей",
    "забудь",
    "отбой",
    "пофиг",
    "передумал",
    "не будем",
    "закрывай",
    "закрой сессию",
    "закрой файл",
    "хватит читать",
    "закончить чтение",
    "закончили с файлом",
    "всё отмена",
    "все отмена",
    "ладно не надо",
    "не надо файл",
    "отмени приём",
    "отмени прием",
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

INGEST_START = (
    "сейчас скину",
    "сейчас пришлю",
    "сейчас отправлю",
    "скину файл",
    "скину файлы",
    "сохрани файл",
    "сохрани файлы",
    "сохрани их",
    "сохрани следующие",
    "положи в хранилище",
    "сохрани в хранилище",
    "сохрани мануал",
    "сохрани мануалы",
    "открой прием файлов",
    "открой приём файлов",
    "жду файлы",
)

INGEST_END = (
    "все файлы",
    "всё",
    "все",
    "готово",
    "хватит",
    "закончили",
    "больше не буду",
    "сохранение закончено",
    "конец загрузки",
    "прием закрыт",
    "приём закрыт",
)

WILL_SEND_RE = re.compile(
    r"(?:^|[^а-яёa-z0-9])"
    r"(?:сейчас\s+|щас?\s+)?"
    r"(?:скину|пришлю|отправлю|жду\s+файл)"
    r"(?:[^а-яёa-z0-9]|$)",
    re.IGNORECASE,
)
WILL_SEND_EXTRA = (
    "вот файл",
    "сейчас файл",
)

NO_SAVE = (
    "не сохраня",
    "без сохран",
    "не клади",
    "не в хранилищ",
    "временно",
    "только прочитай",
    "только посмотри",
    "не надо сохранять",
    "не нужно сохранять",
)


@dataclass
class Intent:
    kind: str
    raw: str


def _will_send_file(low: str) -> bool:
    if WILL_SEND_RE.search(low):
        return True
    return any(x in low for x in WILL_SEND_EXTRA)


def is_abort_phrase(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower().replace("ё", "е")
    if len(t) <= 80 and any(p in low for p in ABORT_PHRASES):
        return True
    return False


def _wants_library_save(low: str) -> bool:
    if any(x in low for x in NO_SAVE):
        return False
    return any(
        x in low
        for x in (
            "сохрани",
            "положи в хранилищ",
            "в хранилище",
            "запиши в баз",
        )
    )


def _is_temp_read_start(low: str) -> bool:
    will_send = _will_send_file(low)
    no_save = any(x in low for x in NO_SAVE)
    read_it = any(
        x in low
        for x in (
            "прочитай",
            "прочти",
            "посмотри",
            "разбери",
            "по этому файл",
            "вопросы по",
            "задам",
            "как будешь отвечать",
            "как будешь ответит",
        )
    )
    about_file = any(
        x in low for x in ("файл", "мануал", "документ", "pdf", "доки", "инструкц")
    )
    if _wants_library_save(low):
        return False
    if will_send and about_file and (no_save or read_it):
        return True
    if no_save and about_file and (will_send or read_it):
        return True
    if will_send and no_save:
        return True
    return False


def classify_intent(text: str) -> Intent:
    t = (text or "").strip()
    if not t:
        return Intent("chat", t)
    if CONFIRM_RE.match(t):
        return Intent("confirm", t)
    if CANCEL_RE.match(t):
        return Intent("cancel", t)

    low = t.lower().replace("ё", "е")

    if is_abort_phrase(t):
        return Intent("abort", t)

    if _is_temp_read_start(low):
        return Intent("temp_read_start", t)

    if any(
        x in low
        for x in (
            "закончили с файлом",
            "закрой временный",
            "убери временный файл",
            "больше вопросов нет",
            "вопросов больше нет",
        )
    ):
        return Intent("temp_read_end", t)

    # docs Q&A — but not if user is about to send a file
    if not _will_send_file(low):
        docs_scope = any(
            x in low
            for x in (
                "мануал",
                "мануалах",
                "файл",
                "файлах",
                "документ",
                "документах",
                "хранилищ",
                "инструкц",
                "pdf",
            )
        )
        docs_ask = any(
            x in low
            for x in (
                "посмотри",
                "прочитай",
                "прочти",
                "найди в",
                "согласно",
                "по мануал",
                "в мануал",
                "в файл",
                "в документ",
                "в хранилищ",
                "что написано",
                "как выполнить",
                "как сделать",
                "как запустить",
                "как провести",
                "aging",
            )
        )
        if docs_scope and docs_ask:
            return Intent("ask_docs", t)
        if "мануал" in low and any(
            x in low for x in ("как", "найди", "посмотри", "где", "что написано", "про ")
        ):
            return Intent("ask_docs", t)

    if (
        any(x in low for x in INGEST_START)
        or (
            "сохрани" in low
            and any(x in low for x in ("файл", "мануал", "документ", "pdf", "их"))
            and not any(x in low for x in ("что сохрани", "что ты сохрани"))
        )
    ) and not any(x in low for x in NO_SAVE):
        return Intent("ingest_start", t)

    if low in INGEST_END or low.startswith("готово") or low in {"все", "всё"}:
        return Intent("ingest_end", t)

    if any(
        x in low
        for x in (
            "возможные пароли",
            "возможный пароль",
            "возможные пароль",
            "кандидаты парол",
            "список парол",
            "попробуй пароли",
            "подбери пароль",
            "подбери пароли",
        )
    ) or (
        ("пароли:" in low or low.startswith("пароли "))
        and "к файлу" not in low
        and "к pdf" not in low
    ):
        return Intent("password_candidates", t)

    if "пароль" in low and any(
        x in low for x in ("файл", "pdf", "к ", "для ", "от ", ":", "id")
    ):
        return Intent("file_password", t)

    if any(
        x in low
        for x in (
            "список файлов",
            "какие файлы",
            "что в хранилище",
            "покажи файлы",
            "мои файлы",
            "мои мануалы",
            "список мануалов",
        )
    ):
        return Intent("list_files", t)

    if any(h in low for h in WEB_HINTS) or low.startswith("найди ") or low.startswith(
        "поищи "
    ):
        if not (
            "день рождения" in low
            or "дни рождения" in low
            or "в базе" in low
            or "что ты записал" in low
            or "мануал" in low
            or "файл" in low
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
