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
    from app.llm.studio_ctl import LoadedInstance

    st = SystemStatus(
        bot_running=True,
        paused=False,
        pause_reason="",
        version="v1.007",
        auto_update=True,
        net=NetProbe(ok=True, latency_ms=40.0, speed_kbps=1500.0, detail="ok"),
        studio=StudioSnapshot(
            server_ok=True,
            chat_model="qwen/qwen3.5-9b",
            vision_model="qwen/qwen3.5-9b",
            chat_loaded=True,
            active_role="чат отвечает · qwen/qwen3.5-9b",
            server_ping_ms=12.0,
            inference_ok=True,
            inference_ms=220.0,
            inference_reply="OK",
            inference_model="qwen/qwen3.5-9b",
            served_ids=["qwen/qwen3.5-9b"],
            loaded=[
                LoadedInstance(
                    model_key="qwen/qwen3.5-9b",
                    instance_id="inst-1",
                    source="native",
                )
            ],
        ),
        web_panel="http://127.0.0.1:8765",
        remote_version="1.007",
        update_available=False,
    )
    html = control_panel_html(st)
    assert "Панель управления" in html
    assert "v1.007" in html
    assert "модель отвечает" in html
    assert "Загружено в память" in html
    assert "актуально" in html
    assert "inst-1" in html
    assert "GPU%" in html
    assert "Интернет" in html
    kb = control_panel_keyboard(paused=False)
    assert kb is not None
    flat = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Тест ИИ" in t for t in flat)
    assert any(b.callback_data == "panel:lm_test" for row in kb.inline_keyboard for b in row)


def test_version_bump_file() -> None:
    root = Path(__file__).resolve().parents[1]
    ver = read_local_version(root)
    assert ver == "1.011"
    assert is_newer(ver, "1.010")
