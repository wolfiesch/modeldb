"""Initialize the local modeldb SQLite database.

Usage:
    python -m db.init
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


DB_DIR = Path(__file__).resolve().parent
DB_PATH = DB_DIR / "modeldb.sqlite"
SCHEMA_PATH = DB_DIR / "schema.sql"
SEED_SOURCES_PATH = DB_DIR / "seed_sources.sql"


def initialize(db_path: Path = DB_PATH) -> list[str]:
    """Apply schema.sql and seed_sources.sql, then return created table names."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    seed_sql = SEED_SOURCES_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_sql)
        conn.executescript(seed_sql)
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

    return [row[0] for row in rows]


def main() -> int:
    tables = initialize()
    print(f"Initialized {DB_PATH}")
    print("Created tables:")
    for table in tables:
        print(f"- {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
