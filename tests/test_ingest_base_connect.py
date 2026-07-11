from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.base import connect


class ConnectMigrationTests(unittest.TestCase):
    def test_connect_adds_model_display_name_column_to_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "modeldb.sqlite"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE model (
                        id INTEGER PRIMARY KEY,
                        canonical_slug TEXT UNIQUE NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            migrated = connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.execute("PRAGMA table_info(model)").fetchall()
                }
            finally:
                migrated.close()

        self.assertIn("display_name", columns)


if __name__ == "__main__":
    unittest.main()
