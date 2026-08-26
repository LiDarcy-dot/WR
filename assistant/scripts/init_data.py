from __future__ import annotations

import argparse
from pathlib import Path

from app.db import init_db
from app.storage_layout import ensure_data_layout


def main() -> None:
    parser = argparse.ArgumentParser(description="Init assistant data folder + DB")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Путь к папке данных, например D:\\WR_Assistant_Data",
    )
    args = parser.parse_args()
    ensure_data_layout(args.data_dir)
    init_db(args.data_dir / "db" / "assistant.sqlite3")
    print(f"OK: структура и БД готовы в {args.data_dir}")


if __name__ == "__main__":
    main()
