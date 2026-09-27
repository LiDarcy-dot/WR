from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.llm.router import ModelRouter, describe_image


METER_VISION_PROMPT = """На фото дисплей электросчётчика или его показания.
Нужны тарифные зоны:
- T1 / Т1 = день (дневные)
- T2 / Т2 = ночь (ночные)
- T3 / Т3 = полупик (если есть)

Ответь ТОЛЬКО JSON без markdown:
{
  "is_meter": true/false,
  "t1": число или null,
  "t2": число или null,
  "t3": число или null,
  "raw_digits": "что видно на табло",
  "confidence": 0.0-1.0,
  "hint": "коротко что на фото"
}
Если это не счётчик — is_meter=false.
Числа без пробелов и единиц, как на табло (можно с десятичной точкой).
"""


@dataclass(frozen=True)
class MeterVisionReading:
    is_meter: bool
    t1: float | None = None
    t2: float | None = None
    t3: float | None = None
    raw_digits: str = ""
    confidence: float = 0.0
    hint: str = ""
    raw_model: str = ""


def _to_float(v) -> float | None:  # noqa: ANN001
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_meter_vision_json(text: str) -> MeterVisionReading:
    raw = (text or "").strip()
    # strip ```json fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        # fallback: scrape T1/T2 from free text
        low = raw.lower().replace("ё", "е")
        t1 = t2 = t3 = None
        for pat, key in (
            (r"т\s*1\s*[:=]?\s*(\d+(?:[.,]\d+)?)", "t1"),
            (r"t\s*1\s*[:=]?\s*(\d+(?:[.,]\d+)?)", "t1"),
            (r"день[^\d]{0,12}(\d+(?:[.,]\d+)?)", "t1"),
            (r"т\s*2\s*[:=]?\s*(\d+(?:[.,]\d+)?)", "t2"),
            (r"t\s*2\s*[:=]?\s*(\d+(?:[.,]\d+)?)", "t2"),
            (r"ночь[^\d]{0,12}(\d+(?:[.,]\d+)?)", "t2"),
            (r"т\s*3\s*[:=]?\s*(\d+(?:[.,]\d+)?)", "t3"),
        ):
            mm = re.search(pat, low)
            if mm:
                val = _to_float(mm.group(1))
                if key == "t1" and t1 is None:
                    t1 = val
                elif key == "t2" and t2 is None:
                    t2 = val
                elif key == "t3" and t3 is None:
                    t3 = val
        is_meter = t1 is not None or t2 is not None
        return MeterVisionReading(
            is_meter=is_meter,
            t1=t1,
            t2=t2,
            t3=t3,
            raw_digits=raw[:200],
            confidence=0.4 if is_meter else 0.0,
            hint="разобрал без JSON",
            raw_model=text or "",
        )
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return MeterVisionReading(is_meter=False, raw_model=text or "")
    return MeterVisionReading(
        is_meter=bool(data.get("is_meter")),
        t1=_to_float(data.get("t1")),
        t2=_to_float(data.get("t2")),
        t3=_to_float(data.get("t3")),
        raw_digits=str(data.get("raw_digits") or ""),
        confidence=float(data.get("confidence") or 0),
        hint=str(data.get("hint") or ""),
        raw_model=text or "",
    )


async def read_meter_from_image(
    router: ModelRouter, *, data_url: str
) -> MeterVisionReading:
    text = await describe_image(
        router, data_url=data_url, user_prompt=METER_VISION_PROMPT
    )
    return parse_meter_vision_json(text)


def caption_suggests_meter(caption: str | None) -> bool:
    low = (caption or "").lower().replace("ё", "е")
    return any(
        x in low
        for x in (
            "показан",
            "счетчик",
            "счётчик",
            "мосэнерго",
            "т1",
            "т2",
            "t1",
            "t2",
            "день",
            "ночь",
            "жкх",
        )
    )


def caption_tariff_hint(caption: str | None) -> str | None:
    """Return 't1' / 't2' / 't3' if caption forces tariff slot."""
    low = (caption or "").lower().replace("ё", "е").strip()
    if re.search(r"(^|\s)(т\s*1|t\s*1|день)(\s|$|:)", low):
        return "t1"
    if re.search(r"(^|\s)(т\s*2|t\s*2|ночь)(\s|$|:)", low):
        return "t2"
    if re.search(r"(^|\s)(т\s*3|t\s*3|полупик)(\s|$|:)", low):
        return "t3"
    return None
