"""Create / migrate the local preset DB and seed the shipped presets (idempotent).

presets.local.db is gitignored: each install keeps its own popular counts, and
new presets from a `git pull` are added here on the next setup or run. On first
run it starts from the legacy committed presets.db, so existing counts carry over.

Usage: python backend/database/prepare_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.db_ops import seed_default_presets  # noqa: E402
from database.init_db import init_db  # noqa: E402


def main() -> int:
    path = init_db()
    seeded = seed_default_presets()
    print(f"Database ready: {path}")
    print(f"Seeded {len(seeded)} new preset(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
