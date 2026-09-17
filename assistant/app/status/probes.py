from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.llm.router import ModelRouter
from app.llm.studio_ctl import StudioSnapshot, fetch_studio_snapshot

log = logging.getLogger(__name__)


@dataclass
class NetProbe:
    ok: bool
    latency_ms: float | None
    speed_kbps: float | None
    detail: str


@dataclass
class SystemStatus:
    bot_running: bool
    paused: bool
    pause_reason: str
    version: str
    auto_update: bool
    net: NetProbe
    studio: StudioSnapshot
    web_panel: str


async def probe_internet() -> NetProbe:
    """Latency to Telegram API + rough download speed via small Cloudflare trace."""
    latency_ms: float | None = None
    speed_kbps: float | None = None
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get("https://api.telegram.org")
            latency_ms = (time.perf_counter() - t0) * 1000
            # ~100KB-ish payload for rough throughput
            t1 = time.perf_counter()
            r2 = await client.get("https://speed.cloudflare.com/__down?bytes=100000")
            dt = max(time.perf_counter() - t1, 1e-6)
            if r2.status_code < 400:
                speed_kbps = (len(r2.content) / 1024.0) / dt
            ok = r.status_code < 500
            detail = f"Telegram HTTP {r.status_code}"
            return NetProbe(ok=ok, latency_ms=latency_ms, speed_kbps=speed_kbps, detail=detail)
    except Exception as exc:  # noqa: BLE001
        return NetProbe(
            ok=False,
            latency_ms=latency_ms,
            speed_kbps=None,
            detail=str(exc)[:160],
        )


async def collect_status(
    *,
    router: ModelRouter,
    paused: bool,
    pause_reason: str,
    version: str,
    auto_update: bool,
    web_port: int,
) -> SystemStatus:
    net = await probe_internet()
    studio = await fetch_studio_snapshot(router)
    return SystemStatus(
        bot_running=True,
        paused=paused,
        pause_reason=pause_reason or "",
        version=version,
        auto_update=auto_update,
        net=net,
        studio=studio,
        web_panel=f"http://127.0.0.1:{web_port}",
    )
