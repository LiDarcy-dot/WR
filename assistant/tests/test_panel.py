from __future__ import annotations

from app.intent import classify_intent
from app.llm.studio_ctl import StudioSnapshot
from app.status.probes import NetProbe, SystemStatus
from app.ui import control_panel_html, control_panel_keyboard
from app.update.versioning import is_newer, read_local_version
from pathlib import Path


def test_control_panel_intent() -> None:
    assert classify_intent("панель").kind == "control_panel"
    assert classify_intent("открой панель управления").kind == "control_panel"


def test_control_panel_render() -> None:
    st = SystemStatus(
        bot_running=True,
        paused=False,
        pause_reason="",
        version="v1.002",
        auto_update=True,
        net=NetProbe(ok=True, latency_ms=40.0, speed_kbps=1500.0, detail="ok"),
        studio=StudioSnapshot(
            server_ok=True,
            chat_model="qwen/qwen3.5-9b",
            vision_model="qwen/qwen3.5-9b",
            chat_loaded=True,
            active_role="чат · qwen/qwen3.5-9b",
            ping_ms=12.0,
        ),
        web_panel="http://127.0.0.1:8765",
    )
    html = control_panel_html(st)
    assert "Панель управления" in html
    assert "v1.002" in html
    assert "Интернет" in html
    kb = control_panel_keyboard(paused=False)
    assert kb is not None


def test_version_bump_file() -> None:
    root = Path(__file__).resolve().parents[1]
    ver = read_local_version(root)
    assert is_newer(ver, "1.001") or ver == "1.002"
