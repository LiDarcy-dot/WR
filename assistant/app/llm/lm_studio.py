from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.actions.models import AssistantReply


SYSTEM_JSON_HINT = """
Когда пользователь хочет СОХРАНИТЬ данные, ответь ТОЛЬКО JSON без markdown:
{
  "mode": "propose_action",
  "message": "краткое пояснение по-русски",
  "action_type": "upsert_person|create_reminder_one_shot|create_reminder_recurring|create_entity_type",
  "payload": { ... }
}
Не пиши «подтверди» обычным текстом — только propose_action JSON.
Программа сама покажет кнопки; пользователь подтвердит Да / + / голосом / кнопкой.

Для обычного разговора, мнений, шуток и вопросов НЕ про сохранение:
{
  "mode": "chat",
  "message": "ответ по-русски",
  "action_type": null,
  "payload": {}
}
Не предлагай сохранить в базу, если пользователь не просил запомнить/записать.
Не утверждай, что у тебя нет базы или памяти — для личных фактов смотри блок ФАКТЫ ИЗ ЛОКАЛЬНОЙ БД.
Не оборачивай JSON в ```.
Примеры payload:
- upsert_person: display_name, relation?, birthday_day?, birthday_month?, birthday_year?, attributes:[{key,label,value,value_type}]
- create_reminder_one_shot: title, fire_at (ISO), body?
- create_reminder_recurring: title, rrule, dtstart (ISO date), time_of_day, body?, human_summary
- create_entity_type: name (latin snake), title, fields:[{key,label,field_type,required}]
"""

WEB_SYSTEM = """Ты помощник с доступом к свежим результатам веб-поиска.
Отвечай по-русски, кратко и по делу.
Опирайся ТОЛЬКО на переданный контекст поиска/страниц. Не выдумывай цены и наличие.
Если данных мало — скажи что не хватает и что проверить вручную.
В конце дай 3–7 ссылок из контекста.
Если речь про покупку в Москве — учитывай доставку/самовывоз, когда это видно в тексте.
Укажи, что цены могли измениться.
"""


THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


class LMStudioClient:
    def __init__(self, base_url: str, model: str, timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": model or self.model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return strip_think(str(content))

    async def chat(
        self,
        *,
        system_prompt: str,
        user_text: str,
        history: list[dict[str, str]] | None = None,
    ) -> AssistantReply:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt + "\n" + SYSTEM_JSON_HINT},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        content = await self._complete(messages, temperature=0.2)
        return parse_model_content(content)

    async def chat_plain(
        self,
        *,
        system_prompt: str,
        user_text: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return await self._complete(messages, temperature=temperature, model=model)

    async def chat_with_image(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_data_url: str,
        temperature: float = 0.1,
        model: str | None = None,
    ) -> str:
        # OpenAI-style multimodal content
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            return await self._complete(
                messages, temperature=temperature, model=model
            )
        except httpx.HTTPStatusError:
            # Some LM Studio builds want raw base64 without data: prefix
            if image_data_url.startswith("data:") and "," in image_data_url:
                raw_b64 = image_data_url.split(",", 1)[1]
                user_content[1] = {
                    "type": "image_url",
                    "image_url": {"url": raw_b64},
                }
                messages[1] = {"role": "user", "content": user_content}
                return await self._complete(
                    messages, temperature=temperature, model=model
                )
            raise

    async def transcribe(
        self, raw: bytes, *, filename: str, model: str | None = None
    ) -> str:
        files = {"file": (filename or "audio.ogg", raw, "application/octet-stream")}
        data = {"model": model or self.model}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("text") or "").strip()
        return str(payload).strip()

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
