from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from app.llm.lm_studio import LMStudioClient

log = logging.getLogger(__name__)


VISION_OCR_PROMPT = """Ты видишь изображение. Ответь по-русски.

1) Если на фото есть текст (документ, экран, вывеска, рукопись) — максимально полно
и аккуратно распознай его, даже если снимок смазан, под углом или с бликами.
Сохрани структуру строк/абзацев.

2) Кратко опиши, что ещё видно на фото (объекты, сцена), если это не только текст.

Формат:
ТЕКСТ:
...
ОПИСАНИЕ:
...
"""


class ModelRouter:
    """
    Temporarily switch LM Studio to a specialist model (vision / whisper),
    then restore the default chat model when possible.
    """

    def __init__(
        self,
        lm: LMStudioClient,
        *,
        chat_model: str,
        vision_model: str | None = None,
        transcribe_model: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self.lm = lm
        self.chat_model = chat_model
        self.vision_model = vision_model or chat_model
        self.transcribe_model = transcribe_model or ""
        # OpenAI compat is .../v1 ; native load API is often .../api/v1
        self.openai_base = lm.base_url.rstrip("/")
        root = self.openai_base
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        self.native_base = (api_base or root).rstrip("/")

    async def list_model_ids(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.openai_base}/models")
                r.raise_for_status()
                data = r.json()
            return [str(x.get("id") or x.get("name") or "") for x in data.get("data", [])]
        except Exception as exc:  # noqa: BLE001
            log.warning("list models failed: %s", exc)
            return []

    def _pick(self, ids: list[str], hints: tuple[str, ...], fallback: str) -> str:
        low_ids = [(i, i.lower()) for i in ids if i]
        for hint in hints:
            for orig, low in low_ids:
                if hint in low:
                    return orig
        return fallback

    async def resolve_vision_model(self) -> str:
        if self.vision_model and self.vision_model != self.chat_model:
            return self.vision_model
        ids = await self.list_model_ids()
        return self._pick(
            ids,
            ("vl", "vision", "qwen2.5-vl", "qwen3-vl", "llava", "minicpm-v"),
            self.vision_model or self.chat_model,
        )

    async def resolve_transcribe_model(self) -> str | None:
        if self.transcribe_model:
            return self.transcribe_model
        ids = await self.list_model_ids()
        picked = self._pick(ids, ("whisper", "speech", "asr", "transcri"), "")
        return picked or None

    async def _load_model(self, model_id: str) -> None:
        # Best-effort: LM Studio native load (0.4+)
        payloads = (
            {"model": model_id},
            {"model_key": model_id},
            {"path": model_id},
        )
        urls = (
            f"{self.native_base}/api/v1/models/load",
            f"{self.native_base}/api/v0/models/load",
        )
        async with httpx.AsyncClient(timeout=300.0) as client:
            for url in urls:
                for payload in payloads:
                    try:
                        r = await client.post(url, json=payload)
                        if r.status_code < 400:
                            log.info("loaded model %s via %s", model_id, url)
                            return
                    except Exception as exc:  # noqa: BLE001
                        log.debug("load %s failed: %s", url, exc)
        # Fallback: just point subsequent requests at the model id
        log.info("using model id without explicit load: %s", model_id)

    async def _unload_model(self, model_id: str) -> None:
        urls = (
            f"{self.native_base}/api/v1/models/unload",
            f"{self.native_base}/api/v0/models/unload",
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            for url in urls:
                try:
                    r = await client.post(url, json={"model": model_id, "instance_id": model_id})
                    if r.status_code < 400:
                        return
                except Exception:
                    continue

    @asynccontextmanager
    async def use_model(self, model_id: str) -> AsyncIterator[str]:
        prev = self.lm.model
        switched = model_id and model_id != prev
        if switched:
            await self._load_model(model_id)
            self.lm.model = model_id
        try:
            yield model_id
        finally:
            if switched:
                # restore chat model for VRAM
                try:
                    await self._unload_model(model_id)
                except Exception:
                    pass
                await self._load_model(self.chat_model)
                self.lm.model = self.chat_model


async def describe_image(
    router: ModelRouter,
    *,
    data_url: str,
    user_prompt: str | None = None,
) -> str:
    model = await router.resolve_vision_model()
    prompt = user_prompt or VISION_OCR_PROMPT
    async with router.use_model(model):
        return await router.lm.chat_with_image(
            system_prompt=(
                "Ты локальный ассистент с зрением. Отвечай по-русски. "
                "Текст на фото распознавай максимально полно."
            ),
            user_text=prompt,
            image_data_url=data_url,
            temperature=0.1,
        )


async def answer_about_image(
    router: ModelRouter,
    *,
    data_url: str,
    question: str,
    prior_notes: str | None = None,
) -> str:
    model = await router.resolve_vision_model()
    extra = f"\nРанее распознано:\n{prior_notes}\n" if prior_notes else ""
    prompt = (
        f"{extra}\nВопрос пользователя: {question}\n"
        "Смотри на изображение и ответь по делу. Если вопрос про текст — "
        "цитируй распознанное."
    )
    async with router.use_model(model):
        return await router.lm.chat_with_image(
            system_prompt="Ты локальный ассистент с зрением. Отвечай по-русски.",
            user_text=prompt,
            image_data_url=data_url,
            temperature=0.2,
        )


async def transcribe_audio(
    router: ModelRouter,
    *,
    raw: bytes,
    filename: str,
) -> str:
    model = await router.resolve_transcribe_model()
    # 1) OpenAI-compatible transcriptions
    if model:
        async with router.use_model(model):
            text = await router.lm.transcribe(raw, filename=filename, model=model)
            if text:
                return text
    # 2) faster-whisper local fallback
    text = _faster_whisper_transcribe(raw, filename)
    if text:
        return text
    raise RuntimeError(
        "Не удалось расшифровать аудио. "
        "Скачай Whisper в LM Studio (если API поддерживает) "
        "или поставь: pip install faster-whisper"
    )


def _faster_whisper_transcribe(raw: bytes, filename: str) -> str | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    import tempfile
    from pathlib import Path

    suffix = Path(filename).suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        path = tmp.name
    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(path, language="ru")
        return " ".join(s.text.strip() for s in segments if s.text).strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("faster-whisper failed: %s", exc)
        return None
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
