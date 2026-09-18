from __future__ import annotations

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
