from __future__ import annotations

import re
from dataclasses import dataclass


READING_HINTS = (
    "показан",
    "мосэнерго",
    "мосэнергосбыт",
    "электр",
    "квт",
    "счетчик",
    "счётчик",
    "жкх",
    "т1",
    "t1",
)

LIST_HINTS = (
    "жкх",
    "мосэнерго",
    "мосэнергосбыт",
    "показания",
    "счетчик",
    "счётчик",
    "электричеств",
)


@dataclass(frozen=True)
class ParsedReading:
    value: float
    meter_number: str | None = None
    note: str | None = None
    t1: float | None = None
    t2: float | None = None
    t3: float | None = None


_NUM = r"(\d+(?:[.,]\d+)?)"


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def looks_like_zhkh_list(text: str) -> bool:
    low = (text or "").lower().replace("ё", "е")
    if not any(h in low for h in LIST_HINTS):
        return False
    ask = any(
        x in low
        for x in (
            "статус",
            "покажи",
            "какие",
            "что с",
            "окно",
            "когда",
            "надо ли",
            "нужно ли",
            "список",
            "кабинет",
            "/zhkh",
        )
    )
    # short commands
    if low.strip() in {
        "жкх",
        "мосэнерго",
        "мосэнергосбыт",
        "показания",
        "счетчики",
        "счётчики",
    }:
        return True
    if ask and any(h in low for h in LIST_HINTS):
        return True
    if "окно" in low and any(h in low for h in ("показан", "жкх", "мосэнерго")):
        return True
    return False


def looks_like_zhkh_mark_sent(text: str) -> bool:
    low = (text or "").lower().replace("ё", "е")
    if not any(h in low for h in ("показан", "мосэнерго", "жкх", "счетчик", "счётчик")):
        # still allow bare phrases
        if not any(x in low for x in ("подал", "отправил", "передал", "внес", "внёс")):
            return False
    return any(
        x in low
        for x in (
            "подал показан",
            "отправил показан",
            "передал показан",
            "внес показан",
            "внёс показан",
            "уже подал",
            "уже отправил",
            "отметь что подал",
            "отметь подачу",
            "подано",
            "отправил в кабинет",
            "внес в кабинет",
            "внёс в кабинет",
        )
    )


def parse_t1_t2_text(text: str) -> ParsedReading | None:
    """Parse 'показания т1 123 т2 456' without requiring other hints beyond tariffs."""
    low = (text or "").lower().replace("ё", "е")
    t1 = t2 = t3 = None
    m1 = re.search(rf"(?:т\s*1|t\s*1|день)\s*[:=]?\s*{_NUM}", low)
    m2 = re.search(rf"(?:т\s*2|t\s*2|ночь)\s*[:=]?\s*{_NUM}", low)
    m3 = re.search(rf"(?:т\s*3|t\s*3)\s*[:=]?\s*{_NUM}", low)
    if m1:
        t1 = _f(m1.group(1))
    if m2:
        t2 = _f(m2.group(1))
    if m3:
        t3 = _f(m3.group(1))
    if t1 is None and t2 is None:
        return None
    note = []
    if t1 is not None:
        note.append(f"T1={t1:g}")
    if t2 is not None:
        note.append(f"T2={t2:g}")
    if t3 is not None:
        note.append(f"T3={t3:g}")
    return ParsedReading(
        value=float(t1 if t1 is not None else t2),
        note="; ".join(note),
        t1=t1,
        t2=t2,
        t3=t3,
    )


def parse_zhkh_reading(text: str) -> ParsedReading | None:
    raw = (text or "").strip()
    if not raw:
        return None
    dual = parse_t1_t2_text(raw)
    if dual and dual.t1 is not None and dual.t2 is not None:
        return dual
    low = raw.lower().replace("ё", "е")
    if not any(h in low for h in READING_HINTS) and not re.search(
        r"\bт[123]\b|\bt[123]\b", low
    ):
        # allow "показания 12345" already covered; bare large number alone — no
        return None
    if dual:
        return dual

    meter_m = re.search(
        r"(?:счетчик|счётчик|пу|№|#)\s*[:=]?\s*(\d{6,12})",
        low,
    )
    meter_number = meter_m.group(1) if meter_m else None
    if not meter_number:
        # known default often mentioned alone
        m2 = re.search(r"\b(14195368)\b", low)
        if m2:
            meter_number = m2.group(1)

    t1 = t2 = t3 = None
    for tariff, key in (("t1", "t1"), ("т1", "t1"), ("t2", "t2"), ("т2", "t2"), ("t3", "t3"), ("т3", "t3")):
        m = re.search(rf"\b{tariff}\b\s*[:=]?\s*{_NUM}", low)
        if m:
            val = _f(m.group(1))
            if key == "t1":
                t1 = val
            elif key == "t2":
                t2 = val
            else:
                t3 = val

    value: float | None = None
    if t1 is not None:
        value = t1
    else:
        patterns = (
            rf"(?:показан\w*|значение|число)\s*[:=]?\s*{_NUM}",
            rf"(?:мосэнерго(?:сбыт)?|электр\w*|квт\.?ч?)\s*[:=]?\s*{_NUM}",
            rf"(?:запиши|запомни|сохрани)\s+(?:показан\w*\s+)?{_NUM}",
        )
        for pat in patterns:
            m = re.search(pat, low)
            if m:
                value = _f(m.group(1))
                break
        if value is None:
            # "показания: 12345" already; last resort — number after hint word
            m = re.search(rf"(?:показан\w*|жкх|мосэнерго)\D{{0,12}}{_NUM}", low)
            if m:
                value = _f(m.group(1))

    if value is None:
        return None

    note_parts = []
    if t1 is not None:
        note_parts.append(f"T1={t1:g}")
    if t2 is not None:
        note_parts.append(f"T2={t2:g}")
    if t3 is not None:
        note_parts.append(f"T3={t3:g}")

    return ParsedReading(
        value=value,
        meter_number=meter_number,
        note="; ".join(note_parts) if note_parts else None,
        t1=t1,
        t2=t2,
        t3=t3,
    )
