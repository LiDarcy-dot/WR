from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".gif",
}


def is_image_name(name: str, mime: str | None = None) -> bool:
    low = (name or "").lower()
    if Path(low).suffix in IMAGE_SUFFIXES:
        return True
    if mime and mime.startswith("image/"):
        return True
    return False


def is_audio_name(name: str, mime: str | None = None) -> bool:
    low = (name or "").lower()
    if Path(low).suffix in {".ogg", ".oga", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".opus"}:
        return True
    if mime and (mime.startswith("audio/") or mime == "application/ogg"):
        return True
    return False


def bytes_to_jpeg_b64(
    raw: bytes, *, source_name: str = "image.bin", max_side: int = 2048
) -> tuple[bytes, str]:
    """
    Normalize any common image (incl. HEIC when pillow-heif is available) to JPEG bytes.
    Returns (jpeg_bytes, data_url).
    """
    img = _open_image(raw, source_name)
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, float(max_side) / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    jpeg = buf.getvalue()
    b64 = base64.b64encode(jpeg).decode("ascii")
    return jpeg, f"data:image/jpeg;base64,{b64}"


def _open_image(raw: bytes, source_name: str):
    suffix = Path(source_name).suffix.lower()
    if suffix in {".heic", ".heif"}:
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "HEIC не открылся. Поставь pillow-heif или пришли JPG/PNG."
            ) from exc
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Нужен Pillow: pip install Pillow") from exc

    try:
        return Image.open(io.BytesIO(raw))
    except Exception as exc:
        if suffix not in {".heic", ".heif"}:
            try:
                from pillow_heif import register_heif_opener

                register_heif_opener()
                return Image.open(io.BytesIO(raw))
            except Exception:
                pass
        raise RuntimeError(f"Не смог открыть изображение ({source_name}): {exc}") from exc
