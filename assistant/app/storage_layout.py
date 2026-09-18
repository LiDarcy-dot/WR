from __future__ import annotations

from pathlib import Path

DATA_SUBDIRS = (
    "db",
    "backups",
    "people",
    "meters",
    "reminders",
    "inbox",
    "documents",
    "mail_cache",
    "gosuslugi_cache",
    "profiles",
)


def ensure_data_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in DATA_SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Папка данных локального ассистента WR.\n"
            "db/ — база SQLite\n"
            "backups/ — ежедневные копии БД\n"
            "inbox/ — сырые файлы до разбора\n"
            "documents/ — разобранные документы\n",
            encoding="utf-8",
        )
