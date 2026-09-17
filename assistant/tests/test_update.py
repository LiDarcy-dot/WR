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
