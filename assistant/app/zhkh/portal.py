from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "mosenergosbyt"


@dataclass
class PortalMeter:
    nn_ls: str
    title: str
    raw: dict[str, Any] = field(default_factory=dict)
    last_t1: float | None = None
    last_t2: float | None = None
    last_t3: float | None = None
    last_dt: str | None = None
    balance: float | None = None
    debt: float | None = None
    nn_days: Any = None


@dataclass
class PortalSubmitResult:
    ok: bool
    message: str
    nn_ls: str | None = None
    t1: float | None = None
    t2: float | None = None


@dataclass
class PortalCheckResult:
    ok: bool
    message: str
    meters: list[PortalMeter] = field(default_factory=list)
    auth_failed: bool = False


def _import_mes():
    try:
        from mosenergosbyt import Account, Session  # type: ignore
        from mosenergosbyt.exceptions import SessionException  # type: ignore
        from mosenergosbyt.meter import MeterException  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Нет пакета mosenergosbyt. В папке Assistant: "
            '.venv\\Scripts\\pip install mosenergosbyt requests'
        ) from exc
    return Account, Session, SessionException, MeterException


def _meter_from_obj(nn_ls: str, meter: Any) -> PortalMeter:
    title = getattr(meter, "nm_ls_group_full", None) or str(nn_ls)
    raw = {
        k: v
        for k, v in getattr(meter, "__dict__", {}).items()
        if k != "session" and not k.startswith("_") and k != "measure_list"
    }
    last_t1 = last_t2 = last_t3 = None
    last_dt = None
    try:
        if getattr(meter, "measure_list", None):
            lm = meter.last_measure
            last_t1 = getattr(lm, "vl_t1", None)
            last_t2 = getattr(lm, "vl_t2", None)
            last_t3 = getattr(lm, "vl_t3", None)
            dt = getattr(lm, "dt_indication", None)
            last_dt = str(dt) if dt else None
    except Exception:
        pass
    bal = getattr(meter, "vl_balance", None)
    debt = getattr(meter, "vl_debt", None)
    nn_days = getattr(meter, "nn_days", None)
    return PortalMeter(
        nn_ls=str(nn_ls),
        title=str(title),
        raw=raw,
        last_t1=_num(last_t1),
        last_t2=_num(last_t2),
        last_t3=_num(last_t3),
        last_dt=last_dt,
        balance=_num(bal),
        debt=_num(debt),
        nn_days=nn_days,
    )


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def login_and_list_meters(login: str, password: str) -> list[PortalMeter]:
    result = check_cabinet(login, password)
    if not result.ok:
        raise RuntimeError(result.message)
    return result.meters


def check_cabinet(login: str, password: str) -> PortalCheckResult:
    Account, Session, SessionException, _MeterException = _import_mes()
    try:
        acc = Account(Session(login=login, password=password))
        acc.get_info(with_measure=True, indications=True, balance=True)
    except SessionException as exc:
        return PortalCheckResult(
            ok=False,
            message=f"Вход в ЛК не удался: {exc}",
            auth_failed=True,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        auth = any(x in msg for x in ("авториз", "парол", "login", "вход", "auth"))
        return PortalCheckResult(
            ok=False,
            message=f"ЛК Мосэнергосбыт недоступен: {exc}",
            auth_failed=auth,
        )

    try:
        meters_map = acc.meter_list
    except Exception as exc:  # noqa: BLE001
        return PortalCheckResult(ok=False, message=f"Не получил список счетов: {exc}")

    meters = [_meter_from_obj(nn_ls, m) for nn_ls, m in meters_map.items()]
    return PortalCheckResult(ok=True, message="ok", meters=meters)


def format_cabinet_report(
    meters: list[PortalMeter],
    *,
    active_meter: str,
    window_label: str,
) -> str:
    import html as html_mod

    def esc(x: object) -> str:
        return html_mod.escape("" if x is None else str(x))

    lines = [
        "<b>Мосэнергосбыт · ЛК</b>",
        f"Окно показаний: {esc(window_label)}",
        f"Активный у бота: <code>{esc(active_meter)}</code>",
        f"Счетов в кабинете: {len(meters)}",
        "",
    ]
    if not meters:
        lines.append("Счетов не видно — проверь, что логин тот.")
        return "\n".join(lines)

    for m in meters:
        mark = ""
        if active_meter and (
            active_meter == m.nn_ls or active_meter in (m.title or "")
            or active_meter in str(m.raw)
        ):
            mark = " ← платим этот"
        lines.append(f"• <code>{esc(m.nn_ls)}</code> — {esc(m.title)}{mark}")
        bits = []
        if m.last_t1 is not None:
            bits.append(f"T1={m.last_t1:g}")
        if m.last_t2 is not None:
            bits.append(f"T2={m.last_t2:g}")
        if m.last_t3 is not None:
            bits.append(f"T3={m.last_t3:g}")
        if bits:
            when = f" ({esc(m.last_dt)})" if m.last_dt else ""
            lines.append("  последние: " + ", ".join(bits) + when)
        if m.balance is not None or m.debt is not None:
            bal = f"{m.balance:g}" if m.balance is not None else "—"
            debt = f"{m.debt:g}" if m.debt is not None else "—"
            lines.append(f"  баланс {esc(bal)} · долг {esc(debt)}")
    lines.append("")
    lines.append(
        "Фото табло с подписью <i>т1</i>/<i>т2</i> — передам в ЛК после Confirm."
    )
    return "\n".join(lines)


def _pick_meter(meters: dict, prefer: str):
    prefer = (prefer or "").strip()
    if prefer and prefer in meters:
        return meters[prefer], prefer
    if prefer:
        for nn_ls, m in meters.items():
            blob = f"{nn_ls} " + " ".join(
                str(v) for v in getattr(m, "__dict__", {}).values() if not callable(v)
            )
            if prefer in blob.replace(" ", ""):
                return m, str(nn_ls)
    if len(meters) == 1:
        nn_ls = next(iter(meters))
        return meters[nn_ls], str(nn_ls)
    return None, None


def submit_readings(
    *,
    login: str,
    password: str,
    meter_number: str,
    t1: float,
    t2: float | None = None,
    t3: float | None = None,
) -> PortalSubmitResult:
    """Upload day/night readings to Mosenergosbyt LK (direct, no Telegram proxy)."""
    Account, Session, SessionException, MeterException = _import_mes()
    try:
        acc = Account(Session(login=login, password=password))
        acc.get_info(with_measure=True, indications=True, balance=False)
    except SessionException as exc:
        return PortalSubmitResult(ok=False, message=f"Вход не удался: {exc}")
    except Exception as exc:  # noqa: BLE001
        return PortalSubmitResult(
            ok=False,
            message=(
                f"Не достучался до my.mosenergosbyt.ru: {exc}. "
                "Проверь интернет без VPN на весь ПК."
            ),
        )

    try:
        meters = acc.meter_list
    except Exception as exc:  # noqa: BLE001
        return PortalSubmitResult(ok=False, message=f"Нет списка счетов: {exc}")

    meter, nn_ls = _pick_meter(meters, meter_number)
    if not meter:
        known = ", ".join(str(k) for k in meters.keys()) or "—"
        return PortalSubmitResult(
            ok=False,
            message=(
                f"Счётчик/ЛС «{meter_number}» не найден среди: {known}. "
                "Пришли лицевой счёт из ЛК или уточни номер."
            ),
        )

    day = int(round(float(t1)))
    night = int(round(float(t2))) if t2 is not None else None
    evening = int(round(float(t3))) if t3 is not None else None
    try:
        if not getattr(meter, "measure_list", None):
            meter.get_measure_list()
        msg = meter.upload_measure(day, night, evening)
        return PortalSubmitResult(
            ok=True,
            message=str(msg) or "Показания переданы",
            nn_ls=nn_ls,
            t1=float(day),
            t2=float(night) if night is not None else None,
        )
    except MeterException as exc:
        return PortalSubmitResult(
            ok=False,
            message=f"Портал отклонил показания: {exc}",
            nn_ls=nn_ls,
            t1=float(day),
            t2=float(night) if night is not None else None,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("upload_measure failed")
        return PortalSubmitResult(
            ok=False,
            message=f"Ошибка передачи: {exc}",
            nn_ls=nn_ls,
        )


_CREDS_RE = re.compile(
    r"(?:логин|login|лк)\s*[:=]?\s*(\S+)\s+"
    r"(?:пароль|password|пасс|pass)\s*[:=]?\s*(.+)$",
    re.IGNORECASE,
)
_CREDS_RE2 = re.compile(
    r"^\s*(\S+)\s*[|/]\s*(.+?)\s*$",
)
_LOGIN_ONLY = re.compile(
    r"^(?:логин|login|лк)\s*[:=]?\s*(\S+)\s*$",
    re.IGNORECASE,
)
_PASS_ONLY = re.compile(
    r"^(?:пароль|password|пасс|pass)\s*[:=]?\s*(.+)$",
    re.IGNORECASE,
)


def parse_credentials_message(text: str) -> tuple[str | None, str | None] | None:
    """Return (login, password). Either part may be None if only one was sent."""
    t = (text or "").strip()
    if not t:
        return None
    m = _CREDS_RE.search(t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    low = t.lower().replace("ё", "е")
    if "мосэнерго" in low or "жкх логин" in low or "логин лк" in low:
        m = re.search(
            r"логин\s*[:=]?\s*(\S+)\s+пароль\s*[:=]?\s*(.+)$",
            t,
            flags=re.I,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()
    m = _LOGIN_ONLY.match(t)
    if m:
        return m.group(1).strip(), None
    m = _PASS_ONLY.match(t)
    if m:
        return None, m.group(1).strip()
    if "|" in t or ("/" in t and "http" not in low):
        m = _CREDS_RE2.match(t)
        if m and len(m.group(1)) >= 3 and len(m.group(2)) >= 3:
            return m.group(1), m.group(2)
    return None


ASK_CREDS_HTML = (
    "Нужен вход в ЛК Мосэнергосбыт.\n"
    "Пришли:\n"
    "<code>логин: ТЕЛЕФОН_ИЛИ_EMAIL_ИЛИ_ЛС пароль: ПАРОЛЬ</code>\n\n"
    "Или по частям:\n"
    "<code>логин: …</code>\n"
    "потом <code>пароль: …</code>\n\n"
    "Не подойдёт — пришли другие. «отмена» — стоп."
)
