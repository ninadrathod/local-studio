"""Initialize the presets SQLite database."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

DATABASE_DIR = Path(__file__).resolve().parent
# Live database: local to each install and gitignored, so `git pull` never
# conflicts with the download counts the app writes.
DB_PATH = DATABASE_DIR / "presets.local.db"
# Older releases committed and wrote `presets.db`. It stays in the repo frozen
# (never written again) so existing clones can pull cleanly; its rows and
# counts are copied into DB_PATH once, the first time DB_PATH is created.
LEGACY_DB_PATH = DATABASE_DIR / "presets.db"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"


POPULAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS popular (
    preset_id INTEGER PRIMARY KEY,
    used_count INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0),
    FOREIGN KEY (preset_id) REFERENCES presets(preset_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_popular_used_count ON popular (used_count DESC);
"""


def _ensure_popular_table(conn: sqlite3.Connection) -> None:
    """Create `popular` and backfill a 0-count row for every preset."""
    conn.executescript(POPULAR_SCHEMA)
    conn.execute(
        """
        INSERT OR IGNORE INTO popular (preset_id, used_count)
        SELECT preset_id, 0 FROM presets
        """
    )


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns/tables introduced after the original schema (existing DBs)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(presets)").fetchall()}
    if not cols:
        return
    if "ar" not in cols:
        conn.execute(
            "ALTER TABLE presets ADD COLUMN ar TEXT NOT NULL DEFAULT 'non-square'"
        )
    if "text_input" not in cols:
        conn.execute(
            "ALTER TABLE presets ADD COLUMN text_input TEXT NOT NULL DEFAULT 'no'"
        )
    if "default_text" not in cols:
        conn.execute(
            "ALTER TABLE presets ADD COLUMN default_text TEXT NOT NULL DEFAULT ''"
        )
    if "text_character_limit" not in cols:
        conn.execute(
            "ALTER TABLE presets ADD COLUMN text_character_limit "
            "INTEGER NOT NULL DEFAULT 0"
        )
    _ensure_popular_table(conn)


def init_db(db_path: Path = DB_PATH) -> Path:
    """Create the database file and apply schema.sql. Returns the db path."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path == DB_PATH and not db_path.exists() and LEGACY_DB_PATH.exists():
        shutil.copyfile(LEGACY_DB_PATH, db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema)
        migrate_schema(conn)
        conn.commit()

    return db_path


if __name__ == "__main__":
    path = init_db()
    print(f"Database ready: {path}")
