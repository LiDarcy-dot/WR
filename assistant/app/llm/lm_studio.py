from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.actions.models import AssistantReply


SYSTEM_JSON_HINT = """
Когда пользователь хочет СОХРАНИТЬ данные, ответь ТОЛЬКО JSON без markdown-ограждений:
{
  "mode": "propose_action",
  "message": "краткое пояснение по-русски",
  "action_type": "upsert_person|create_reminder_one_shot|create_reminder_recurring|create_entity_type",
  "payload": { ... }
}

Для обычного разговора:
{
  "mode": "chat",
  "message": "ответ по-русски",
  "action_type": null,
  "payload": {}
}

Не пиши рассуждения вне JSON. Не оборачивай JSON в ```.
Примеры payload:
- upsert_person: display_name, relation?, birthday_day?, birthday_month?, birthday_year?, attributes:[{key,label,value,value_type}]
- create_reminder_one_shot: title, fire_at (ISO), body?
- create_reminder_recurring: title, rrule, dtstart (ISO date), time_of_day, body?, human_summary
- create_entity_type: name (latin snake), title, fields:[{key,label,field_type,required}]
"""

THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


class LMStudioClient:
    def __init__(self, base_url: str, model: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        *,
        system_prompt: str,
        user_text: str,
        history: list[dict[str, str]] | None = None,
    ) -> AssistantReply:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt + "\n" + SYSTEM_JSON_HINT},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        # некоторые reasoning-сборки кладут мысль отдельно
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return parse_model_content(str(content))

    async def healthcheck(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/models")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def parse_model_content(content: str) -> AssistantReply:
    text = strip_think(content)
    # убрать markdown fences если модель всё же обернула
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        return AssistantReply.model_validate_json(text)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            raw: dict[str, Any] = json.loads(match.group(0))
            return AssistantReply.model_validate(raw)
        except Exception:
            pass

    return AssistantReply(mode="chat", message=text or content.strip())
