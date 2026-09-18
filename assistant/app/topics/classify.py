from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TopicUnderstanding:
    mode: str
    title_norm: str
    label_ru: str
    summary_ru: str
    will_do_ru: str


# (mode, keywords) — matched against lowercased title
_MODE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "inbox",
        (
            "inbox",
            "in-box",
            "incoming",
            "dump",
            "raw",
            "catch",
            "buffer",
            "inbox",
            "входящ",
            "инбокс",
            "свалк",
            "черновик",
            "inbox",
        ),
    ),
    (
        "life",
        (
            "life",
            "calendar",
            "schedule",
            "reminder",
            "reminders",
            "birthday",
            "birthdays",
            "agenda",
            "plans",
            "жизнь",
            "календар",
            "напомина",
            "др",
            "расписан",
            "планы",
        ),
    ),
    (
        "people",
        (
            "people",
            "person",
            "persons",
            "family",
            "contacts",
            "friends",
            "relatives",
            "люди",
            "человек",
            "семь",
            "контакт",
            "родствен",
            "друзья",
        ),
    ),
    (
        "docs",
        (
            "doc",
            "docs",
            "document",
            "documents",
            "file",
            "files",
            "manual",
            "manuals",
            "pdf",
            "library",
            "архив",
            "документ",
            "файл",
            "мануал",
            "инструкц",
            "библиоте",
        ),
    ),
    (
        "chat",
        (
            "chat",
            "think",
            "thinking",
            "brain",
            "llm",
            "ai",
            "gpt",
            "qwen",
            "random",
            "ideas",
            "размыш",
            "мозг",
            "болтовн",
            "свободн",
            "идеи",
        ),
    ),
    (
        "system",
        (
            "system",
            "status",
            "bot",
            "admin",
            "settings",
            "setup",
            "control",
            "panel",
            "систем",
            "статус",
            "настрой",
            "админ",
            "панель",
        ),
    ),
    (
        "home",
        (
            "home",
            "house",
            "zhkh",
            "utility",
            "utilities",
            "bills",
            "meters",
            "дом",
            "квартир",
            "жкх",
            "счет",
            "счёт",
            "показан",
        ),
    ),
]

_MODE_COPY: dict[str, tuple[str, str, str]] = {
    "inbox": (
        "Входящие / Inbox",
        "Сюда складываем сырое: мысли, «запиши», пока без разбора.",
        "Буду принимать быстрые заметки и предлагать сохранить "
        "(человек, напоминание, файл), если попросишь.",
    ),
    "life": (
        "Жизнь / календарь",
        "Тема про время: напоминания, даты, дни рождения, «скоро».",
        "Буду ловить напоминания и календарные просьбы; "
        "подтверждение — кнопкой или «да».",
    ),
    "people": (
        "Люди",
        "Карточки людей, родство, факты, дни рождения.",
        "Буду обновлять людей и дни рождения в локальной базе "
        "после твоего подтверждения.",
    ),
    "docs": (
        "Документы / файлы",
        "Мануалы, PDF, «сохрани файл», вопросы по хранилищу.",
        "Буду принимать файлы в библиотеку и отвечать по мануалам "
        "(поиск по индексу).",
    ),
    "chat": (
        "Свободный чат",
        "Разговор с моделью без обязательной записи в базу.",
        "Буду просто отвечать. В базу — только если явно попросишь сохранить.",
    ),
    "system": (
        "Система",
        "Статус бота, LM Studio, пауза, обновления.",
        "Буду отвечать про статус и управление; бытовую болтовню лучше "
        "в другие темы.",
    ),
    "home": (
        "Дом / ЖКХ",
        "Счета, показания, дом/квартира.",
        "Буду помогать с заметками по дому и ЖКХ; сохранение — по подтверждению.",
    ),
    "general": (
        "General",
        "Общая тема форума (корень).",
        "Краткий пульт: могу подсказать команды и куда писать. "
        "Рабочие дела лучше в отдельных темах.",
    ),
    "custom": (
        "Свой кабинет",
        "Название не совпало с типовыми кабинетами — работаю как гибкая тема.",
        "Буду отвечать в контексте названия темы. Сохранять в базу — "
        "только по явной просьбе.",
    ),
}


def _norm(title: str) -> str:
    t = (title or "").strip().lower()
    t = t.replace("ё", "е")
    t = re.sub(r"[^\w\s\-+/&]+", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify_topic(title: str, *, is_general: bool = False) -> TopicUnderstanding:
    if is_general or not (title or "").strip() or title.strip().lower() in {
        "general",
        "общий",
        "общее",
    }:
        label, summary, will = _MODE_COPY["general"]
        return TopicUnderstanding(
            mode="general",
            title_norm=title or "General",
            label_ru=label,
            summary_ru=summary,
            will_do_ru=will,
        )

    n = _norm(title)
    tokens = set(n.replace("-", " ").replace("/", " ").split())
    best: str | None = None
    for mode, keys in _MODE_KEYWORDS:
        for key in keys:
            k = key.lower()
            if k in n or k in tokens:
                best = mode
                break
            # prefix for short latin keys
            if len(k) >= 3 and any(tok.startswith(k) for tok in tokens):
                best = mode
                break
        if best:
            break

    mode = best or "custom"
    label, summary, will = _MODE_COPY[mode]
    if mode == "custom":
        summary = (
            f"Тема «{title.strip()}»: отдельный кабинет под это название."
        )
    return TopicUnderstanding(
        mode=mode,
        title_norm=title.strip(),
        label_ru=label,
        summary_ru=summary,
        will_do_ru=will,
    )


def format_hello_html(u: TopicUnderstanding, *, is_new: bool) -> str:
    head = "Новая тема" if is_new else "Тема"
    return (
        f"<b>{head}: {html_escape(u.title_norm)}</b>\n"
        f"Как понял: <b>{html_escape(u.label_ru)}</b> "
        f"(режим <code>{html_escape(u.mode)}</code>)\n\n"
        f"{html_escape(u.summary_ru)}\n\n"
        f"<b>Что буду делать здесь</b>\n{html_escape(u.will_do_ru)}\n\n"
        f"<i>Это служебное сообщение удалю через 24 часа.</i>"
    )


def html_escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
