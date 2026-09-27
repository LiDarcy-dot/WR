from __future__ import annotations

from pathlib import Path

from app import vault
from app.db import connect, init_db
from app.zhkh.portal import parse_credentials_message
from app.zhkh.vision_readings import parse_meter_vision_json


def test_parse_creds() -> None:
    assert parse_credentials_message("логин: 79001112233 пароль: secret") == (
        "79001112233",
        "secret",
    )
    assert parse_credentials_message("логин me@x.ru пароль q w e")[0] == "me@x.ru"


def test_vault_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "v.sqlite3"
    init_db(db)
    conn = connect(db)
    vault.upsert_credential(
        conn, tmp_path, service="mosenergosbyt", login="u1", password="p@ss"
    )
    got = vault.get_credential(conn, tmp_path, "mosenergosbyt")
    assert got == ("u1", "p@ss")


def test_meter_vision_json() -> None:
    r = parse_meter_vision_json(
        '{"is_meter": true, "t1": 12345, "t2": 678, "t3": null, "confidence": 0.9}'
    )
    assert r.is_meter and r.t1 == 12345 and r.t2 == 678
    r2 = parse_meter_vision_json("на фото т1: 100 т2: 200")
    assert r2.t1 == 100 and r2.t2 == 200
