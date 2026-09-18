from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.files import temp_session
from app.llm.router import ModelRouter, describe_image, transcribe_audio
from app.media.images import bytes_to_jpeg_b64, is_audio_name, is_image_name

log = logging.getLogger(__name__)


@dataclass
class AnalyzedMedia:
    name: str
    kind: str  # text|image|audio|unknown
    text: str
    path: str | None
    image_data_url: str | None
    needs_password: bool
    summary: str


async def analyze_bytes(
    *,
    conn,
    data_root: Path,
    router: ModelRouter,
    raw: bytes,
    original_name: str,
    mime: str | None = None,
) -> AnalyzedMedia:
    name = original_name or "file"

    if is_image_name(name, mime):
        path = temp_session.save_raw_temp(data_root, raw, name)
        try:
            _jpeg, data_url = bytes_to_jpeg_b64(raw, source_name=name)
        except Exception as exc:  # noqa: BLE001
            return AnalyzedMedia(
                name=name,
                kind="image",
                text="",
                path=path,
                image_data_url=None,
                needs_password=False,
                summary=f"Фото сохранил временно, но не открыл: {exc}",
            )
        try:
            vision_text = await describe_image(router, data_url=data_url)
        except Exception as exc:  # noqa: BLE001
            log.exception("vision failed")
            return AnalyzedMedia(
                name=name,
                kind="image",
                text="",
                path=path,
                image_data_url=data_url,
                needs_password=False,
                summary=(
                    f"Фото есть, vision не ответил: {exc}. "
                    "Проверь, что в LM Studio загружена vision-модель "
                    "(или укажи LM_STUDIO_VISION_MODEL)."
                ),
            )
        return AnalyzedMedia(
            name=name,
            kind="image",
            text=vision_text,
            path=path,
            image_data_url=data_url,
            needs_password=False,
            summary="Фото разобрал через vision (временно, без хранилища).",
        )

    if is_audio_name(name, mime) or (mime and "ogg" in mime):
        path = temp_session.save_raw_temp(data_root, raw, name)
        try:
            transcript = await transcribe_audio(
                router, raw=raw, filename=name
            )
        except Exception as exc:  # noqa: BLE001
            return AnalyzedMedia(
                name=name,
                kind="audio",
                text="",
                path=path,
                image_data_url=None,
                needs_password=False,
                summary=f"Аудио сохранил временно, расшифровка не вышла: {exc}",
            )
        return AnalyzedMedia(
            name=name,
            kind="audio",
            text=transcript,
            path=path,
            image_data_url=None,
            needs_password=False,
            summary="Аудио расшифровал (временно).",
        )

    # documents / unknown: try text extract
    body, err, path = temp_session.load_bytes_to_temp_text(
        conn, data_root, raw, name
    )
    if err == "password":
        return AnalyzedMedia(
            name=name,
            kind="text",
            text="",
            path=path,
            image_data_url=None,
            needs_password=True,
            summary="Файл запаролен.",
        )
    if err == "empty" and is_image_name(name, mime):
        # fallback already handled
        pass
    if err and err != "empty":
        return AnalyzedMedia(
            name=name,
            kind="unknown",
            text="",
            path=path,
            image_data_url=None,
            needs_password=False,
            summary=f"Не разобрал: {err}",
        )
    if err == "empty":
        # maybe it's an image mislabeled — try vision
        try:
            _jpeg, data_url = bytes_to_jpeg_b64(raw, source_name=name)
            vision_text = await describe_image(router, data_url=data_url)
            return AnalyzedMedia(
                name=name,
                kind="image",
                text=vision_text,
                path=path,
                image_data_url=data_url,
                needs_password=False,
                summary="Разобрал как изображение через vision.",
            )
        except Exception:
            return AnalyzedMedia(
                name=name,
                kind="unknown",
                text="",
                path=path,
                image_data_url=None,
                needs_password=False,
                summary="Текста нет (скан/неизвестный формат). Vision тоже не смог.",
            )
    return AnalyzedMedia(
        name=name,
        kind="text",
        text=body,
        path=path,
        image_data_url=None,
        needs_password=False,
        summary="Документ прочитал (временно).",
    )
