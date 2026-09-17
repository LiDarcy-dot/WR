from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from app.update.versioning import (
    format_version,
    is_newer,
    normalize_version,
    read_local_version,
)

log = logging.getLogger(__name__)

COPY_NAMES = (
    "app",
    "main.py",
    "requirements.txt",
    "VERSION",
    "START_BOT.bat",
    "scripts",
    "SETUP_PC.md",
)


@dataclass
class UpdatePlan:
    local: str
    remote: str
    branch: str
    repo: str


@dataclass
class UpdateOutcome:
    ok: bool
    local: str
    remote: str
    message: str
    backup_dir: str | None = None
    restored: bool = False


@dataclass
class VersionCheck:
    local: str
    remote: str
    newer: bool
    error: str | None = None


def result_path(install_root: Path) -> Path:
    return install_root / ".update_result.json"


def write_result(install_root: Path, payload: dict) -> None:
    result_path(install_root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def consume_result(install_root: Path) -> dict | None:
    path = result_path(install_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    return data if isinstance(data, dict) else None


def _branch_ref(branch: str) -> str:
    """Encode branch names that contain slashes (cursor/...)."""
    return quote(branch, safe="")


async def fetch_remote_version(
    *,
    repo: str,
    branch: str,
    timeout: float = 30.0,
) -> str:
    ref = _branch_ref(branch)
    urls = (
        f"https://raw.githubusercontent.com/{repo}/{ref}/assistant/VERSION",
        f"https://raw.githubusercontent.com/{repo}/{branch}/assistant/VERSION",
    )
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                r.raise_for_status()
                return normalize_version(r.text)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    raise RuntimeError(f"VERSION fetch failed: {last_err}")


async def probe_versions(
    install_root: Path,
    *,
    repo: str,
    branch: str,
) -> VersionCheck:
    local = read_local_version(install_root)
    try:
        remote = await fetch_remote_version(repo=repo, branch=branch)
    except Exception as exc:  # noqa: BLE001
        return VersionCheck(local=local, remote="?", newer=False, error=str(exc)[:300])
    return VersionCheck(
        local=local, remote=remote, newer=is_newer(remote, local), error=None
    )


async def check_for_update(
    install_root: Path,
    *,
    repo: str,
    branch: str,
) -> UpdatePlan | None:
    info = await probe_versions(install_root, repo=repo, branch=branch)
    log.info(
        "update check: local=%s remote=%s newer=%s err=%s root=%s",
        info.local,
        info.remote,
        info.newer,
        info.error,
        install_root,
    )
    if info.error:
        raise RuntimeError(info.error)
    if not info.newer:
        return None
    return UpdatePlan(
        local=info.local, remote=info.remote, branch=branch, repo=repo
    )


def _backup_tree(install_root: Path, backups_root: Path, local_ver: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backups_root / f"pre_update_{normalize_version(local_ver)}_{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in COPY_NAMES:
        src = install_root / name
        if not src.exists():
            continue
        target = dest / name
        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    db = install_root / "db" / "assistant.sqlite3"
    if db.exists():
        (dest / "db").mkdir(parents=True, exist_ok=True)
        shutil.copy2(db, dest / "db" / "assistant.sqlite3")
    meta = {
        "backed_up_at": ts,
        "local_version": local_ver,
        "install_root": str(install_root),
    }
    (dest / "backup_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dest


def _restore_backup(install_root: Path, backup_dir: Path) -> None:
    for name in COPY_NAMES:
        src = backup_dir / name
        if not src.exists():
            continue
        dst = install_root / name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    db_src = backup_dir / "db" / "assistant.sqlite3"
    if db_src.exists():
        db_dst = install_root / "db" / "assistant.sqlite3"
        db_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_src, db_dst)


def _download_branch_zip(repo: str, branch: str, dest_zip: Path) -> None:
    ref = _branch_ref(branch)
    urls = (
        f"https://codeload.github.com/{repo}/zip/refs/heads/{ref}",
        f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}",
        f"https://github.com/{repo}/archive/refs/heads/{ref}.zip",
        f"https://github.com/{repo}/archive/refs/heads/{branch}.zip",
    )
    last_err: Exception | None = None
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        for url in urls:
            try:
                with client.stream("GET", url) as r:
                    r.raise_for_status()
                    with dest_zip.open("wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
                if dest_zip.stat().st_size > 1000:
                    return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
    raise RuntimeError(f"zip download failed: {last_err}")


def _find_assistant_dir(extract_root: Path) -> Path:
    for path in extract_root.rglob("VERSION"):
        parent = path.parent
        if (parent / "app").is_dir() and (parent / "main.py").exists():
            return parent
        if parent.name == "assistant" and (parent / "app").is_dir():
            return parent
    raise FileNotFoundError("assistant/VERSION not found in downloaded zip")


def _replace_from_source(install_root: Path, source_assistant: Path) -> None:
    for name in COPY_NAMES:
        src = source_assistant / name
        if not src.exists():
            continue
        dst = install_root / name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def _pip_install(install_root: Path) -> None:
    py = install_root / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = install_root / ".venv" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)
    req = install_root / "requirements.txt"
    cmd = [str(py), "-m", "pip", "install", "-q", "-r", str(req)]
    proc = subprocess.run(cmd, cwd=str(install_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"pip failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:800]}"
        )


def apply_update(
    install_root: Path,
    plan: UpdatePlan,
    *,
    backups_root: Path,
) -> UpdateOutcome:
    backup_dir: Path | None = None
    try:
        backups_root.mkdir(parents=True, exist_ok=True)
        backup_dir = _backup_tree(install_root, backups_root, plan.local)
        log.info("backup at %s", backup_dir)

        with tempfile.TemporaryDirectory(prefix="wr-upd-") as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "branch.zip"
            _download_branch_zip(plan.repo, plan.branch, zip_path)
            extract_dir = tmp_path / "ext"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            source = _find_assistant_dir(extract_dir)
            remote_ver = normalize_version(
                (source / "VERSION").read_text(encoding="utf-8")
            )
            if not is_newer(remote_ver, plan.local):
                return UpdateOutcome(
                    ok=False,
                    local=plan.local,
                    remote=remote_ver,
                    message="В архиве версия не новее локальной — пропуск.",
                    backup_dir=str(backup_dir),
                )
            _replace_from_source(install_root, source)
            _pip_install(install_root)

        write_result(
            install_root,
            {
                "ok": True,
                "from": plan.local,
                "to": remote_ver,
                "backup_dir": str(backup_dir),
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return UpdateOutcome(
            ok=True,
            local=plan.local,
            remote=remote_ver,
            message=(
                f"Обновлено {format_version(plan.local)} → {format_version(remote_ver)}"
            ),
            backup_dir=str(backup_dir),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("update failed")
        restored = False
        if backup_dir and backup_dir.exists():
            try:
                _restore_backup(install_root, backup_dir)
                restored = True
            except Exception as restore_exc:  # noqa: BLE001
                log.exception("restore failed: %s", restore_exc)
        write_result(
            install_root,
            {
                "ok": False,
                "from": plan.local,
                "to": plan.remote,
                "backup_dir": str(backup_dir) if backup_dir else None,
                "restored": restored,
                "error": str(exc)[:1000],
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return UpdateOutcome(
            ok=False,
            local=plan.local,
            remote=plan.remote,
            message=f"Обновление не удалось: {exc}",
            backup_dir=str(backup_dir) if backup_dir else None,
            restored=restored,
        )


def schedule_restart(install_root: Path) -> None:
    """Start a new bot process hidden (call AFTER stopping polling)."""
    py = install_root / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = install_root / ".venv" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)
    main_py = install_root / "main.py"
    env = os.environ.copy()
    env["WR_UPDATED"] = "1"

    if sys.platform == "win32":
        helper = install_root / "_wr_restart.cmd"
        helper.write_text(
            "\r\n".join(
                [
                    "@echo off",
                    "timeout /t 2 /nobreak >nul",
                    f'cd /d "{install_root}"',
                    f'"{py}" "{main_py}"',
                ]
            ),
            encoding="utf-8",
        )
        flags = 0x00000008 | 0x00000200 | 0x08000000
        subprocess.Popen(
            ["cmd.exe", "/c", str(helper)],
            cwd=str(install_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
        return

    subprocess.Popen(
        [str(py), str(main_py)],
        cwd=str(install_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
