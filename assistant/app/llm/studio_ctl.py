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


@dataclass
class StudioSnapshot:
    server_ok: bool
    error: str | None = None
    available: list[str] = field(default_factory=list)
    loaded: list[LoadedInstance] = field(default_factory=list)
    chat_model: str = ""
    vision_model: str = ""
    transcribe_model: str = ""
    chat_loaded: bool = False
    vision_capable_loaded: bool = False
    active_role: str = "нет"
    ping_ms: float | None = None


async def fetch_studio_snapshot(router: ModelRouter) -> StudioSnapshot:
    snap = StudioSnapshot(
        server_ok=False,
        chat_model=router.chat_model,
        vision_model=router.vision_model or router.chat_model,
        transcribe_model=router.transcribe_model or "",
    )
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # OpenAI list (usually currently served models)
            r = await client.get(f"{router.openai_base}/models")
            snap.ping_ms = (time.perf_counter() - t0) * 1000
            if r.status_code >= 400:
                snap.error = f"LM Studio HTTP {r.status_code}"
                return snap
            snap.server_ok = True
            data = r.json()
            snap.available = [
                str(x.get("id") or x.get("name") or "")
                for x in data.get("data", [])
                if x.get("id") or x.get("name")
            ]

            # Native list with loaded_instances
            try:
                nr = await client.get(f"{router.native_base}/api/v1/models")
                if nr.status_code < 400:
                    ndata = nr.json()
                    models = ndata if isinstance(ndata, list) else ndata.get("models") or ndata.get("data") or []
                    for m in models:
                        key = str(m.get("key") or m.get("id") or m.get("display_name") or "")
                        caps = m.get("capabilities") or {}
                        vision = bool(caps.get("vision"))
                        for inst in m.get("loaded_instances") or []:
                            iid = str(inst.get("id") or inst.get("instance_id") or key)
                            snap.loaded.append(
                                LoadedInstance(
                                    model_key=key,
                                    instance_id=iid,
                                    type=str(m.get("type") or "llm"),
                                    vision=vision,
                                )
                            )
                        if key and key not in snap.available:
                            snap.available.append(key)
            except Exception as exc:  # noqa: BLE001
                log.debug("native models list failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        snap.error = str(exc)[:200]
        snap.ping_ms = (time.perf_counter() - t0) * 1000
        return snap

    # If native loaded empty, treat openai /models as loaded set
    if not snap.loaded and snap.available:
        for mid in snap.available:
            low = mid.lower()
            snap.loaded.append(
                LoadedInstance(
                    model_key=mid,
                    instance_id=mid,
                    vision=("vl" in low or "vision" in low),
                )
            )

    loaded_ids = {x.instance_id for x in snap.loaded} | {x.model_key for x in snap.loaded}
    snap.chat_loaded = any(
        router.chat_model == x or router.chat_model in x or x in router.chat_model
        for x in loaded_ids
    ) or (
        bool(snap.loaded)
        and any(router.chat_model.split("/")[-1] in x for x in loaded_ids)
    )
    # softer match
    if not snap.chat_loaded and snap.loaded:
        chat_tail = router.chat_model.lower().split("/")[-1][:12]
        snap.chat_loaded = any(chat_tail in x.model_key.lower() for x in snap.loaded)

    snap.vision_capable_loaded = any(x.vision for x in snap.loaded)
    if snap.chat_loaded:
        snap.active_role = f"чат · {router.chat_model}"
    elif snap.loaded:
        snap.active_role = f"загружено: {snap.loaded[0].model_key}"
    else:
        snap.active_role = "модель не загружена"
    return snap


async def connect_chat_model(router: ModelRouter) -> str:
    """Ensure LM Studio is up and chat model is loaded."""
    snap = await fetch_studio_snapshot(router)
    if not snap.server_ok:
        return f"LM Studio недоступна: {snap.error or 'нет ответа на :1234'}"

    # Prefer exact configured id; else pick closest from available
    target = router.chat_model
    ids = snap.available or await router.list_model_ids()
    if target not in ids and ids:
        # fuzzy
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

    # verify with tiny completion
    try:
        ok = await router.lm.healthcheck()
        if not ok:
            return f"Модель {target} указана, но healthcheck не прошёл"
        # optional ping chat
        await router.lm.chat_plain(
            system_prompt="ok",
            user_text="Ответь одним словом: готов",
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"Загрузка {target} запрошена, но ответ модели не получен: {exc}. "
            "Проверь, что Local Server в LM Studio включён."
        )
    return f"ИИ подключена как чат: {target}"


async def disconnect_models(router: ModelRouter) -> str:
    snap = await fetch_studio_snapshot(router)
    if not snap.server_ok:
        return f"LM Studio недоступна: {snap.error or 'нет ответа'}"
    if not snap.loaded:
        return "Нечего выгружать — модели не загружены."
    errors = []
    for inst in snap.loaded:
        try:
            await router.unload_model(inst.instance_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{inst.instance_id}: {exc}")
    if errors:
        return "Выгрузка с ошибками: " + "; ".join(errors[:3])
    return f"Выгрузил моделей: {len(snap.loaded)}"
