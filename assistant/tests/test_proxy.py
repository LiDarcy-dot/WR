from __future__ import annotations

from pathlib import Path

from app.bot import _mask_proxy


def test_mask_proxy_hides_password() -> None:
    assert (
        _mask_proxy("socks5://tgproxy:s3cret@1.2.3.4:1080")
        == "socks5://tgproxy:***@1.2.3.4:1080"
    )
    assert _mask_proxy("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"
    assert _mask_proxy("") == "(none)"


def test_telethon_proxy_parse() -> None:
    from app.topics.list_mtproto import _telethon_proxy

    t = _telethon_proxy("socks5://u:p@10.0.0.1:1080")
    assert t is not None
    assert t[1] == "10.0.0.1"
    assert t[2] == 1080
    assert t[4] == "u"
    assert t[5] == "p"
    assert _telethon_proxy("") is None


def test_ensure_telegram_proxy_writes_env(tmp_path: Path, monkeypatch) -> None:
    from app.proxy_ensure import ensure_telegram_proxy, read_default_proxy

    (tmp_path / "proxy.default").write_text(
        "socks5://tgproxy:secret@9.9.9.9:1080\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=x\nTELEGRAM_OWNER_ID=1\n", encoding="utf-8"
    )
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)

    url = ensure_telegram_proxy(tmp_path)
    assert url == "socks5h://tgproxy:secret@9.9.9.9:1080"
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_PROXY=socks5h://tgproxy:secret@9.9.9.9:1080" in text
    assert text.lstrip("\ufeff").startswith("TELEGRAM")
    # idempotent
    assert ensure_telegram_proxy(tmp_path) == url
    assert read_default_proxy(tmp_path).startswith("socks5h://")


def test_ensure_overwrites_empty_proxy(tmp_path: Path, monkeypatch) -> None:
    from app.proxy_ensure import ensure_telegram_proxy

    (tmp_path / "proxy.default").write_text(
        "socks5h://u:p@1.2.3.4:1080\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_PROXY=\nTELEGRAM_BOT_TOKEN=x\n", encoding="utf-8"
    )
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    ensure_telegram_proxy(tmp_path)
    assert "TELEGRAM_PROXY=socks5h://u:p@1.2.3.4:1080" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")


def test_proxy_default_shipped() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = (root / "proxy.default").read_text(encoding="utf-8").strip()
    assert raw.startswith("socks5h://")
    assert "@" in raw
    assert ":1080" in raw
