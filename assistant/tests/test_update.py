from __future__ import annotations

from pathlib import Path

from app.update.versioning import (
    format_version,
    is_newer,
    normalize_version,
    parse_version,
    read_local_version,
)
from app.update.apply import _backup_tree, _restore_backup, write_result, consume_result


def test_version_compare() -> None:
    assert normalize_version("v1.001") == "1.001"
    assert parse_version("1.001") == (1, 1)
    assert parse_version("1.010") == (1, 10)
    assert is_newer("1.002", "1.001")
    assert is_newer("1.010", "1.009")
    assert not is_newer("1.001", "1.001")
    assert not is_newer("1.000", "1.001")
    assert format_version("1.001") == "v1.001"


def test_backup_and_restore(tmp_path: Path) -> None:
    root = tmp_path / "Assistant"
    (root / "app").mkdir(parents=True)
    (root / "app" / "x.py").write_text("old", encoding="utf-8")
    (root / "VERSION").write_text("1.001\n", encoding="utf-8")
    (root / "main.py").write_text("main", encoding="utf-8")
    (root / "requirements.txt").write_text("x\n", encoding="utf-8")
    (root / "db").mkdir()
    (root / "db" / "assistant.sqlite3").write_bytes(b"sqlite")

    backups = tmp_path / "backups"
    bdir = _backup_tree(root, backups, "1.001")
    assert (bdir / "app" / "x.py").read_text(encoding="utf-8") == "old"
    assert (bdir / "db" / "assistant.sqlite3").exists()

    (root / "app" / "x.py").write_text("new-broken", encoding="utf-8")
    _restore_backup(root, bdir)
    assert (root / "app" / "x.py").read_text(encoding="utf-8") == "old"


def test_update_result_roundtrip(tmp_path: Path) -> None:
    write_result(tmp_path, {"ok": True, "to": "1.002"})
    data = consume_result(tmp_path)
    assert data and data["ok"] is True
    assert consume_result(tmp_path) is None


def test_read_local_version(tmp_path: Path) -> None:
    assert read_local_version(tmp_path) == "0.000"
    (tmp_path / "VERSION").write_text("1.001\n", encoding="utf-8")
    assert read_local_version(tmp_path) == "1.001"


def test_schedule_restart_writes_helper(tmp_path: Path) -> None:
    import sys

    import pytest

    from app.update.apply import schedule_restart

    if sys.platform != "win32":
        pytest.skip("restart helper cmd is Windows-specific")

    (tmp_path / "main.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "START_BOT.bat").write_text("@echo off\n", encoding="utf-8")
    schedule_restart(tmp_path, delay_sec=3)
    helper = tmp_path / "_wr_restart.cmd"
    ps1 = tmp_path / "_wr_restart.ps1"
    assert helper.exists()
    assert ps1.exists()
    text = ps1.read_text(encoding="utf-8")
    assert "Stop-Process" in text
    assert "START_BOT.bat" in text or "Start-Process" in text
    assert (tmp_path / "logs" / "restart.log").exists()


def test_version_is_1010() -> None:
    root = Path(__file__).resolve().parents[1]
    assert read_local_version(root) == "1.011"
    assert is_newer("1.011", "1.010")


def test_hard_restart_under_watchdog_exits_only(monkeypatch, tmp_path: Path) -> None:
    from app.update import apply as apply_mod

    scheduled: list[Path] = []
    exits: list[int] = []

    monkeypatch.setenv("WR_WATCHDOG", "1")
    monkeypatch.setattr(
        apply_mod, "schedule_restart", lambda root, delay_sec=5: scheduled.append(root)
    )

    def fake_exit(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(apply_mod.os, "_exit", fake_exit)

    try:
        apply_mod.hard_restart(tmp_path, delay_sec=3)
    except SystemExit as exc:
        assert int(exc.code) == 0
    assert scheduled == []
    assert exits == [0]


def test_request_restart_schedules_then_exits(monkeypatch, tmp_path: Path) -> None:
    from app.update import apply as apply_mod

    called: list[Path] = []

    def fake_schedule(root: Path, *, delay_sec: int = 5) -> None:
        called.append(root)

    exits: list[int] = []

    monkeypatch.setattr(apply_mod, "schedule_restart", fake_schedule)
    monkeypatch.setattr(apply_mod.os, "_exit", lambda code: exits.append(code))

    class FakeApp:
        def __init__(self) -> None:
            self.bot_data = {"install_root": tmp_path}

    apply_mod.request_restart(FakeApp())
    assert called == [tmp_path]
    assert exits == [0]
