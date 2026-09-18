"""
Детект «в игре через Steam» (Windows).

v1: проверка процессов из списка.
Позже можно расширить через Steam API / registry.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class GamePresence:
    in_game: bool
    detail: str = ""


def detect_steam_game(extra_process_names: list[str] | None = None) -> GamePresence:
    if sys.platform != "win32":
        return GamePresence(False, "not_windows")

    try:
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"],
            text=True,
            encoding="cp866",
            errors="ignore",
        )
    except Exception as exc:  # noqa: BLE001
        return GamePresence(False, f"tasklist_error:{exc}")

    names = {line.split(",")[0].strip('"').lower() for line in out.splitlines() if line}
    steam_running = "steam.exe" in names
    watch = {n.lower() for n in (extra_process_names or [])}
    hit = sorted(watch & names)
    if hit:
        return GamePresence(True, f"process:{hit[0]}")
    if steam_running:
        return GamePresence(False, "steam_launcher_only")
    return GamePresence(False, "idle")
