from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Fallback if proxy.default is missing (same SOCKS on NL VPS for Telegram only).
_FALLBACK_PROXY = "socks5h://tgproxy:2G99IVcdJzSr1w@31.15.16.97:1080"

_PROXY_LINE_RE = re.compile(r"^\s*TELEGRAM_PROXY\s*=\s*(.*)$", re.IGNORECASE)


def install_root_from_here() -> Path:
    """Folder with main.py / VERSION (Desktop\\Assistant)."""
    return Path(__file__).resolve().parents[1]


def normalize_proxy_url(value: str) -> str:
    s = str(value or "").strip().lstrip("\ufeff").strip().strip('"').strip("'")
    if not s:
        return ""
    if s.startswith("socks5://"):
        s = "socks5h://" + s[len("socks5://") :]
    return s


def read_default_proxy(install_root: Path | None = None) -> str:
    root = install_root or install_root_from_here()
    path = root / "proxy.default"
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
            if raw and ord(raw[0]) == 0xFEFF:
                raw = raw[1:]
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                return normalize_proxy_url(line)
        except OSError:
            pass
    return normalize_proxy_url(_FALLBACK_PROXY)


def _read_env_proxy(env_file: Path) -> str:
    if not env_file.is_file():
        return ""
    try:
        raw = env_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    if raw and ord(raw[0]) == 0xFEFF:
        raw = raw[1:]
    for line in raw.splitlines():
        m = _PROXY_LINE_RE.match(line)
        if m:
            return normalize_proxy_url(m.group(1))
    return ""


def write_telegram_proxy_env(env_file: Path, proxy: str) -> bool:
    """Insert or replace TELEGRAM_PROXY in .env (UTF-8 no BOM). Returns True if changed."""
    proxy = normalize_proxy_url(proxy)
    if not proxy:
        return False
    if not env_file.is_file():
        return False

    raw = env_file.read_text(encoding="utf-8")
    if raw and ord(raw[0]) == 0xFEFF:
        raw = raw[1:]
    lines = raw.splitlines()
    out: list[str] = []
    found = False
    changed = False
    for line in lines:
        if _PROXY_LINE_RE.match(line):
            new_line = f"TELEGRAM_PROXY={proxy}"
            out.append(new_line)
            found = True
            if line.strip() != new_line:
                changed = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip() != "":
            out.append("")
        out.append(f"TELEGRAM_PROXY={proxy}")
        changed = True

    if not changed:
        return False

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    env_file.write_text(text, encoding="utf-8", newline="\n")
    return True


def ensure_telegram_proxy(install_root: Path | None = None) -> str:
    """Ensure TELEGRAM_PROXY is set in .env and process env. Returns URL used."""
    root = install_root or install_root_from_here()
    desired = read_default_proxy(root)
    if not desired:
        return ""

    env_file = root / ".env"
    current = normalize_proxy_url(os.environ.get("TELEGRAM_PROXY", ""))
    if not current:
        current = _read_env_proxy(env_file)

    # Always pin to proxy.default so TimedOut installs recover without notepad.
    if current != desired:
        try:
            if write_telegram_proxy_env(env_file, desired):
                log.info("TELEGRAM_PROXY written to .env (auto)")
            elif env_file.is_file():
                log.warning("Could not update TELEGRAM_PROXY in %s", env_file)
            else:
                log.warning("No .env at %s — set TELEGRAM_PROXY in environment", root)
        except OSError as exc:
            log.warning("Failed writing TELEGRAM_PROXY: %s", exc)

    os.environ["TELEGRAM_PROXY"] = desired
    return desired
