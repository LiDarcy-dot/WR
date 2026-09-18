from __future__ import annotations

import re
from pathlib import Path


def version_file(install_root: Path) -> Path:
    return install_root / "VERSION"


def read_local_version(install_root: Path) -> str:
    path = version_file(install_root)
    if not path.exists():
        return "0.000"
    return normalize_version(path.read_text(encoding="utf-8").strip() or "0.000")


def normalize_version(text: str) -> str:
    t = (text or "").strip().lstrip("vV").strip()
    # keep digits and dots only
    m = re.search(r"\d+(?:\.\d+)*", t)
    return m.group(0) if m else "0.000"


def parse_version(text: str) -> tuple[int, ...]:
    parts = normalize_version(text).split(".")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out) if out else (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def format_version(text: str) -> str:
    return f"v{normalize_version(text)}"
