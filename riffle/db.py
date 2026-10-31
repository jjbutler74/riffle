from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = "2"

# Bump when the scan starts extracting new per-photo metadata. Rows scanned
# under an older version get their metadata re-read on the next rescan even
# if the file itself hasn't changed.
METADATA_VERSION = 2

_DDL = """
CREATE TABLE IF NOT EXISTS photos (
  id              INTEGER PRIMARY KEY,
  path            TEXT NOT NULL UNIQUE,
  root_folder     TEXT NOT NULL,
  size            INTEGER NOT NULL,
  mtime           REAL NOT NULL,
  content_hash    TEXT NOT NULL,
  date_display    TEXT NOT NULL,
  date_epoch      REAL NOT NULL,
  date_source     TEXT NOT NULL CHECK(date_source IN ('exif','mtime')),
  title           TEXT,
  description     TEXT,
  latitude        REAL,
  longitude       REAL,
  location        TEXT,
  meta_version    INTEGER NOT NULL DEFAULT 1,
  missing_at      REAL,
  first_seen_at   REAL NOT NULL,
  last_scanned_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_missing ON photos(missing_at);

CREATE TABLE IF NOT EXISTS shuffle_order (
  position  INTEGER PRIMARY KEY,
  photo_id  INTEGER NOT NULL UNIQUE REFERENCES photos(id)
);

CREATE TABLE IF NOT EXISTS app_state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# Columns added after schema v1, for upgrading databases created before them.
_ADDED_COLUMNS = {
    "latitude": "REAL",
    "longitude": "REAL",
    "location": "TEXT",
    "meta_version": "INTEGER NOT NULL DEFAULT 1",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    for name, decl in _ADDED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {name} {decl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    _add_missing_columns(conn)
    cur = conn.execute("SELECT value FROM app_state WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO app_state(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
    elif row[0] != SCHEMA_VERSION:
        set_state(conn, "schema_version", SCHEMA_VERSION)
    conn.commit()


def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    cur = conn.execute("SELECT value FROM app_state WHERE key=?", (key,))
    row = cur.fetchone()
    return row["value"] if row is not None else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
