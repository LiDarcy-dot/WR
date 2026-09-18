from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from app.llm.router import ModelRouter

log = logging.getLogger(__name__)


@dataclass
class LoadedInstance:
    model_key: str
    instance_id: str
    type: str = "llm"
    vision: bool = False
    source: str = "native"  # native | openai_guess


@dataclass
class StudioSnapshot:
    server_ok: bool
    error: str | None = None
    available: list[str] = field(default_factory=list)
    loaded: list[LoadedInstance] = field(default_factory=list)
    served_ids: list[str] = field(default_factory=list)  # from /v1/models
    chat_model: str = ""
    vision_model: str = ""
    transcribe_model: str = ""
    chat_loaded: bool = False
    vision_capable_loaded: bool = False
    active_role: str = "нет"
    server_ping_ms: float | None = None
    inference_ok: bool | None = None
    inference_ms: float | None = None
    inference_reply: str | None = None
    inference_model: str | None = None
    # compatibility alias used by older panel code
    ping_ms: float | None = None


def _match_model(configured: str, candidates: set[str]) -> bool:
    if not configured or not candidates:
        return False
    if configured in candidates:
        return True
    low = configured.lower()
    tail = low.split("/")[-1]
    for c in candidates:
        cl = c.lower()
        if low == cl or tail in cl or cl in low:
            return True
        # qwen3.5-9b vs qwen3.5-9b-instruct etc.
        if tail[:10] and tail[:10] in cl:
            return True
    return False


async def fetch_studio_snapshot(
    router: ModelRouter, *, probe_inference: bool = False
) -> StudioSnapshot:
    snap = StudioSnapshot(
        server_ok=False,
        chat_model=router.chat_model,
        vision_model=router.vision_model or router.chat_model,
        transcribe_model=router.transcribe_model or "",
    )
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{router.openai_base}/models")
            snap.server_ping_ms = (time.perf_counter() - t0) * 1000
            snap.ping_ms = snap.server_ping_ms
            if r.status_code >= 400:
                snap.error = f"LM Studio HTTP {r.status_code}"
                return snap
            snap.server_ok = True
            data = r.json()
            snap.served_ids = [
                str(x.get("id") or x.get("name") or "")
                for x in data.get("data", [])
                if x.get("id") or x.get("name")
            ]
            snap.available = list(snap.served_ids)

            # Native list — authoritative for loaded_instances
            native_ok = False
            try:
                nr = await client.get(f"{router.native_base}/api/v1/models")
                if nr.status_code < 400:
                    native_ok = True
                    ndata = nr.json()
                    models = (
                        ndata
                        if isinstance(ndata, list)
                        else ndata.get("models") or ndata.get("data") or []
                    )
                    for m in models:
                        key = str(
                            m.get("key") or m.get("id") or m.get("display_name") or ""
                        )
                        caps = m.get("capabilities") or {}
                        vision = bool(caps.get("vision"))
                        instances = m.get("loaded_instances") or []
                        for inst in instances:
                            iid = str(
                                inst.get("id")
                                or inst.get("instance_id")
                                or key
                            )
                            snap.loaded.append(
                                LoadedInstance(
                                    model_key=key or iid,
                                    instance_id=iid,
                                    type=str(m.get("type") or "llm"),
                                    vision=vision,
                                    source="native",
                                )
                            )
                        if key and key not in snap.available:
                            snap.available.append(key)
            except Exception as exc:  # noqa: BLE001
                log.debug("native models list failed: %s", exc)

            # Only if native API missing: treat /v1/models as "possibly loaded"
            if not native_ok and not snap.loaded and snap.served_ids:
                for mid in snap.served_ids:
                    low = mid.lower()
                    snap.loaded.append(
                        LoadedInstance(
                            model_key=mid,
                            instance_id=mid,
                            vision=("vl" in low or "vision" in low),
                            source="openai_guess",
                        )
                    )
    except Exception as exc:  # noqa: BLE001
        snap.error = str(exc)[:200]
        snap.server_ping_ms = (time.perf_counter() - t0) * 1000
        snap.ping_ms = snap.server_ping_ms
        return snap

    loaded_keys = {x.model_key for x in snap.loaded} | {
        x.instance_id for x in snap.loaded
    }
    # /v1/models lists catalog/served ids — NOT proof of VRAM load.
    # Trust only loaded_instances (native) or openai_guess fallback entries.
    snap.chat_loaded = _match_model(router.chat_model, loaded_keys)
    snap.vision_capable_loaded = any(x.vision for x in snap.loaded)

    if snap.chat_loaded and snap.loaded:
        matched = next(
            (
                x
                for x in snap.loaded
                if _match_model(router.chat_model, {x.model_key, x.instance_id})
            ),
            snap.loaded[0],
        )
        snap.active_role = f"в VRAM · {matched.model_key}"
        snap.inference_model = matched.instance_id or matched.model_key
    elif snap.loaded:
        snap.active_role = f"в VRAM (не конфиг): {snap.loaded[0].model_key}"
        snap.inference_model = snap.loaded[0].instance_id
    elif snap.served_ids:
        snap.active_role = (
            f"сервер есть, в VRAM пусто · каталог: {snap.served_ids[0]}"
        )
        snap.inference_model = router.chat_model or snap.served_ids[0]
    else:
        snap.active_role = "модель не загружена в VRAM"
        snap.inference_model = router.chat_model

    if probe_inference and snap.server_ok:
        await _probe_inference(router, snap)
    return snap


async def _probe_inference(router: ModelRouter, snap: StudioSnapshot) -> None:
    model = snap.inference_model or router.chat_model or router.lm.model
    t0 = time.perf_counter()
    try:
        # temporarily point client at detected model
        prev = router.lm.model
        router.lm.model = model
        reply = await router.lm.chat_plain(
            system_prompt="Ответь очень коротко.",
            user_text="Напиши ровно: OK",
            temperature=0,
        )
        router.lm.model = prev
        snap.inference_ms = (time.perf_counter() - t0) * 1000
        snap.inference_ok = True
        snap.inference_reply = (reply or "").strip()[:80]
        snap.inference_model = model
        if "ok" in (reply or "").lower():
            snap.active_role = f"чат отвечает · {model}"
        else:
            snap.active_role = f"чат отвечает (странно) · {model}"
    except Exception as exc:  # noqa: BLE001
        snap.inference_ms = (time.perf_counter() - t0) * 1000
        snap.inference_ok = False
        snap.inference_reply = str(exc)[:120]
        snap.active_role = f"сервер есть, модель НЕ отвечает · {model}"


async def connect_chat_model(router: ModelRouter) -> str:
    """Ensure LM Studio is up and chat model is loaded + answering."""
    snap = await fetch_studio_snapshot(router, probe_inference=False)
    if not snap.server_ok:
        return f"LM Studio недоступна: {snap.error or 'нет ответа на :1234'}"

    target = router.chat_model
    ids = snap.available or await router.list_model_ids()
    if target not in ids and ids:
        tail = target.lower().split("/")[-1]
        for mid in ids:
            if tail in mid.lower() or mid.lower() in target.lower():
                target = mid
                break

    try:
        await router.load_model(target)
        router.lm.model = target
        router.chat_model = target
    except Exception as exc:  # noqa: BLE001
        return f"Не загрузил {target}: {exc}"

    verify = await fetch_studio_snapshot(router, probe_inference=True)
    if verify.inference_ok:
        return (
            f"ИИ подключена и отвечает как чат: {target}\n"
            f"Ответ теста: {verify.inference_reply!r} · {verify.inference_ms:.0f} мс"
        )
    return (
        f"Загрузка {target} запрошена, но ответ не получен: "
        f"{verify.inference_reply or verify.error or 'нет ответа'}. "
        "В LM Studio: Developer → Local Server On, модель в Loaded."
    )


async def test_inference(router: ModelRouter) -> str:
    snap = await fetch_studio_snapshot(router, probe_inference=True)
    if not snap.server_ok:
        return f"LM Studio недоступна: {snap.error}"
    if snap.inference_ok:
        return (
            f"✅ Модель отвечает.\n"
            f"model: <code>{snap.inference_model}</code>\n"
            f"ответ: {snap.inference_reply}\n"
            f"время: {snap.inference_ms:.0f} мс\n"
            f"На время генерации GPU% обычно растёт; в простое 1–6% — норма."
        )
    return (
        f"❌ Модель не ответила.\n"
        f"Сервер: {'ок' if snap.server_ok else 'нет'}\n"
        f"Загружено: {', '.join(x.model_key for x in snap.loaded) or 'пусто'}\n"
        f"Ошибка: {snap.inference_reply}"
    )


async def disconnect_models(router: ModelRouter) -> str:
    snap = await fetch_studio_snapshot(router, probe_inference=False)
    if not snap.server_ok:
        return f"LM Studio недоступна: {snap.error or 'нет ответа'}"
    if not snap.loaded:
        return "Нечего выгружать — loaded_instances пусто."
    errors = []
    for inst in snap.loaded:
        try:
            await router.unload_model(inst.instance_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst.instance_id}: {exc}")
    if errors:
        return "Выгрузка с ошибками: " + "; ".join(errors[:3])
    return f"Выгрузил моделей: {len(snap.loaded)}"
