from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def extract_text_pages(
    path: Path, *, password: str | None = None
) -> tuple[list[tuple[int, str]], str | None]:
    """
    Returns ([(page_number_1based, text), ...], error).
    error == 'password' if encrypted and password missing/wrong.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, password=password)
    if suffix in {".docx"}:
        return _extract_docx(path)
    if suffix in {".txt", ".md", ".csv", ".log", ".json"}:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            return [], str(exc)
        return ([(1, text)] if text.strip() else []), None
    # images / unknown: no text yet
    return [], None


def _extract_pdf(
    path: Path, *, password: str | None = None
) -> tuple[list[tuple[int, str]], str | None]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        return [], f"pypdf missing: {exc}"

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            return [], "password"
        return [], str(exc)

    if reader.is_encrypted:
        pwd = password or ""
        try:
            ok = reader.decrypt(pwd)
        except Exception:
            return [], "password"
        if ok == 0 and pwd == "":
            return [], "password"
        if ok == 0:
            return [], "password"

    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            pages.append((i, text))
    return pages, None


def _extract_docx(path: Path) -> tuple[list[tuple[int, str]], str | None]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        return [], f"python-docx missing: {exc}"
    try:
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
    return ([(1, text)] if text else []), None


def pages_to_chunks(
    pages: list[tuple[int, str]], *, max_chars: int = 1200
) -> list[tuple[int | None, int, str]]:
    chunks: list[tuple[int | None, int, str]] = []
    idx = 0
    for page, text in pages:
        text = " ".join(text.split())
        if not text:
            continue
        if len(text) <= max_chars:
            chunks.append((page, idx, text))
            idx += 1
            continue
        start = 0
        while start < len(text):
            piece = text[start : start + max_chars]
            chunks.append((page, idx, piece))
            idx += 1
            start += max_chars
    return chunks
