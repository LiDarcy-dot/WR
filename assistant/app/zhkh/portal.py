from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

SERVICE = "mosenergosbyt"


@dataclass
class PortalMeter:
    nn_ls: str
    title: str
    raw: dict[str, Any]


@dataclass
class PortalSubmitResult:
    ok: bool
    message: str
    nn_ls: str | None = None
    t1: float | None = None
    t2: float | None = None


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


def login_and_list_meters(login: str, password: str) -> list[PortalMeter]:
    Account, Session, SessionException, _MeterException = _import_mes()
    try:
        acc = Account(Session(login=login, password=password))
        acc.get_info(with_measure=True, indications=True, balance=False)
    except SessionException as exc:
        raise RuntimeError(f"Вход в ЛК не удался: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ЛК Мосэнергосбыт недоступен: {exc}") from exc

    out: list[PortalMeter] = []
    try:
        meters = acc.meter_list
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Не получил список счетов: {exc}") from exc
    for nn_ls, meter in meters.items():
        title = getattr(meter, "nm_ls_group_full", None) or str(nn_ls)
        raw = {
            k: v
            for k, v in getattr(meter, "__dict__", {}).items()
            if k != "session" and not k.startswith("_")
        }
        out.append(PortalMeter(nn_ls=str(nn_ls), title=str(title), raw=raw))
    return out


def _pick_meter(meters: dict, prefer: str):
    prefer = (prefer or "").strip()
    if prefer and prefer in meters:
        return meters[prefer], prefer
    # match any string field containing the device/account number
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
        # ensure measure history loaded for upload_measure.last_measure
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


def parse_credentials_message(text: str) -> tuple[str, str] | None:
    t = (text or "").strip()
    if not t:
        return None
    m = _CREDS_RE.search(t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # «мосэнерго логин xxx пароль yyy»
    low = t.lower().replace("ё", "е")
    if "мосэнерго" in low or "жкх логин" in low or "логин лк" in low:
        m = re.search(
            r"логин\s*[:=]?\s*(\S+)\s+пароль\s*[:=]?\s*(.+)$",
            t,
            flags=re.I,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()
    if "|" in t or "/" in t and "http" not in low:
        m = _CREDS_RE2.match(t)
        if m and len(m.group(1)) >= 3 and len(m.group(2)) >= 3:
            return m.group(1), m.group(2)
    return None
