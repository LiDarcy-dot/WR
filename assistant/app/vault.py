from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def vault_key_path(data_dir: Path) -> Path:
    return Path(data_dir) / ".vault_key"


def load_or_create_fernet(data_dir: Path) -> Fernet:
    path = vault_key_path(data_dir)
    if path.is_file():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key)


def encrypt_secret(data_dir: Path, plaintext: str) -> str:
    token = load_or_create_fernet(data_dir).encrypt(plaintext.encode("utf-8"))
    return base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_secret(data_dir: Path, blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    try:
        return load_or_create_fernet(data_dir).decrypt(raw).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Не смог расшифровать секрет (сменился .vault_key?)") from exc


def upsert_credential(
    conn: sqlite3.Connection,
    data_dir: Path,
    *,
    service: str,
    login: str,
    password: str,
) -> None:
    blob = encrypt_secret(data_dir, password)
    conn.execute(
        """
        INSERT INTO credentials (service, login, secret_encrypted, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(service) DO UPDATE SET
            login = excluded.login,
            secret_encrypted = excluded.secret_encrypted,
            updated_at = datetime('now')
        """,
        (service, login, blob),
    )
    conn.commit()


def get_credential(
    conn: sqlite3.Connection,
    data_dir: Path,
    service: str,
) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT login, secret_encrypted FROM credentials WHERE service = ?",
        (service,),
    ).fetchone()
    if not row or not row["secret_encrypted"]:
        return None
    password = decrypt_secret(data_dir, row["secret_encrypted"])
    return (row["login"] or "", password)


def has_credential(conn: sqlite3.Connection, service: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM credentials WHERE service = ? LIMIT 1",
        (service,),
    ).fetchone()
    return bool(row)
