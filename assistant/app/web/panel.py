from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.calendar_view import events_for_month, week_agenda
from app.config import Settings
from app.db import connect, init_db
from app.db import repo
from app.memory.formatters import today_in_tz
from app.storage_layout import ensure_data_layout


def create_web_app(settings: Settings) -> FastAPI:
    ensure_data_layout(settings.assistant_data_dir)
    init_db(settings.db_path)

    app = FastAPI(title="WR")
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def db() -> sqlite3.Connection:
        conn = connect(settings.db_path)
        repo.ensure_runtime_schema(conn)
        return conn

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        conn = db()
        today = today_in_tz(settings.timezone)
        week = week_agenda(conn, today, settings.timezone, 7)
        people = repo.list_people(conn)
        paused = repo.is_paused(conn)
        conn.close()

        week_html = []
        for d, events in week:
            if events:
                bits = " · ".join(e.title for e in events[:4])
                week_html.append(
                    f'<a class="day has" href="/day/{d.isoformat()}">'
                    f"<b>{d.strftime('%d.%m')}</b><span>{_esc(bits)}</span></a>"
                )
            else:
                week_html.append(
                    f'<a class="day" href="/day/{d.isoformat()}">'
                    f"<b>{d.strftime('%d.%m')}</b><span>—</span></a>"
                )

        people_html = "".join(
            f"<li>{_esc(p['display_name'])}"
            f"{(' · ' + _esc(p['relation'])) if p['relation'] else ''}</li>"
            for p in people[:40]
        ) or "<li class='muted'>пусто</li>"

        pause_btn = "снять паузу" if paused else "пауза"
        pause_action = "/resume" if paused else "/pause"
        state = "пауза" if paused else "на связи"

        return _shell(
            f"""
            <header>
              <div>
                <h1>WR</h1>
                <p class="muted">{state}</p>
              </div>
              <form method="post" action="{pause_action}">
                <button type="submit">{pause_btn}</button>
              </form>
            </header>
            <section>
              <div class="row">
                <h2>скоро</h2>
                <a href="/calendar">месяц</a>
              </div>
              <div class="week">{''.join(week_html)}</div>
            </section>
            <section>
              <h2>люди</h2>
              <ul>{people_html}</ul>
            </section>
            """
        )

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar(year: int | None = None, month: int | None = None) -> str:
        conn = db()
        today = today_in_tz(settings.timezone)
        y = year or today.year
        m = month or today.month
        marked = events_for_month(conn, y, m, settings.timezone)
        conn.close()
        from app.calendar_view import month_grid, month_title, shift_month

        py, pm = shift_month(y, m, -1)
        ny, nm = shift_month(y, m, 1)
        cells = []
        for week in month_grid(y, m):
            for day in week:
                if day is None:
                    cells.append('<div class="cell empty"></div>')
                    continue
                d = f"{y:04d}-{m:02d}-{day:02d}"
                cls = "cell"
                if day in marked:
                    cls += " has"
                if y == today.year and m == today.month and day == today.day:
                    cls += " today"
                cells.append(f'<a class="{cls}" href="/day/{d}">{day}</a>')

        return _shell(
            f"""
            <header>
              <a href="/">←</a>
              <h1>{month_title(y, m)}</h1>
              <div class="nav">
                <a href="/calendar?year={py}&month={pm}">‹</a>
                <a href="/calendar?year={ny}&month={nm}">›</a>
              </div>
            </header>
            <div class="dow"><span>пн</span><span>вт</span><span>ср</span>
            <span>чт</span><span>пт</span><span>сб</span><span>вс</span></div>
            <div class="grid">{''.join(cells)}</div>
            """
        )

    @app.get("/day/{iso}", response_class=HTMLResponse)
    def day_view(iso: str) -> str:
        from datetime import date

        conn = db()
        d = date.fromisoformat(iso)
        events = events_for_month(conn, d.year, d.month, settings.timezone).get(
            d.day, []
        )
        conn.close()
        if events:
            items = "".join(
                f"<li><b>{_esc(e.title)}</b>"
                f"<div class='muted'>{_esc(e.detail)}</div></li>"
                for e in events
            )
        else:
            items = "<li class='muted'>пусто</li>"
        return _shell(
            f"""
            <header>
              <a href="/calendar?year={d.year}&month={d.month}">←</a>
              <h1>{d.strftime('%d.%m.%Y')}</h1>
            </header>
            <ul>{items}</ul>
            <p class="muted">добавить: напиши боту или укажи дату в чате</p>
            """
        )

    @app.post("/pause")
    def pause() -> RedirectResponse:
        conn = db()
        repo.set_paused(conn, True, "web")
        conn.commit()
        conn.close()
        return RedirectResponse("/", status_code=303)

    @app.post("/resume")
    def resume() -> RedirectResponse:
        conn = db()
        repo.set_paused(conn, False)
        conn.commit()
        conn.close()
        return RedirectResponse("/", status_code=303)

    @app.get("/api/status")
    def api_status() -> dict:
        conn = db()
        out = {
            "paused": repo.is_paused(conn),
            "people": len(repo.list_people(conn)),
            "birthdays": len(repo.list_birthdays(conn)),
        }
        conn.close()
        return out

    return app


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _shell(body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WR</title>
<link rel="stylesheet" href="/static/panel.css"/>
</head>
<body>
<main>{body}</main>
</body>
</html>"""


def run_web(settings: Settings, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_web_app(settings), host=host, port=port, log_level="warning")
