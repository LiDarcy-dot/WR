from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as: python scripts/init_data.py from Assistant root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import init_db
from app.storage_layout import ensure_data_layout


def main() -> None:
    parser = argparse.ArgumentParser(description="Init assistant data folder + DB")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Path to data folder, e.g. Desktop\\Assistant",
    )
    args = parser.parse_args()
    ensure_data_layout(args.data_dir)
    init_db(args.data_dir / "db" / "assistant.sqlite3")
    print(f"OK: data layout and DB ready in {args.data_dir}")


if __name__ == "__main__":
    main()
