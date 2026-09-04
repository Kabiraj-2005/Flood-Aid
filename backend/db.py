"""
Database layer.

SQLite for now so it runs anywhere with no setup. Swap to Postgres + PostGIS
later — the SQL below is deliberately plain so the move is small.

The report table IS the schema the whole team agreed on. Do not change a
column name without telling everyone.
"""

import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "floodaid.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    -- identity: made on the PHONE, not here. This is what stops duplicates.
    id                    TEXT PRIMARY KEY,
    device_id             TEXT NOT NULL,
    counter               INTEGER NOT NULL DEFAULT 0,   -- rises on every edit
    phone_time            INTEGER NOT NULL,             -- ms, phone clock (untrusted)

    -- where it came from
    source                TEXT NOT NULL DEFAULT 'volunteer',  -- volunteer|responder|aerial
    text                  TEXT DEFAULT '',
    photo_ids             TEXT DEFAULT '[]',            -- json list

    -- location: a point, or a polygon for aerial
    lat                   REAL,
    lon                   REAL,
    polygon               TEXT,                         -- json [[lat,lon],...]
    location_confidence   REAL DEFAULT 1.0,

    -- extracted fields
    people_count          INTEGER,
    injured               INTEGER DEFAULT 0,
    children_elderly      INTEGER DEFAULT 0,
    water_level           TEXT,                         -- ankle|knee|waist|above
    rising                INTEGER DEFAULT 0,
    road_passable         TEXT DEFAULT 'unknown',       -- yes|no|unknown

    -- pipeline state
    extraction_confidence REAL DEFAULT 0.0,
    severity              REAL DEFAULT 0.0,
    override_by           TEXT,
    override_reason       TEXT,
    status                TEXT NOT NULL DEFAULT 'new',  -- new|reviewed|assigned|resolved
    cluster_id            TEXT,

    reported_at           INTEGER NOT NULL,             -- server ms
    synced_at             INTEGER NOT NULL,             -- server ms
    updated_at            INTEGER NOT NULL              -- server ms, drives delta sync
);

CREATE INDEX IF NOT EXISTS idx_reports_updated ON reports(updated_at);
CREATE INDEX IF NOT EXISTS idx_reports_status  ON reports(status);

CREATE TABLE IF NOT EXISTS safe_zones (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    capacity  INTEGER NOT NULL DEFAULT 0,
    occupied  INTEGER NOT NULL DEFAULT 0,
    status    TEXT NOT NULL DEFAULT 'open'   -- open|full|closed
);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("photo_ids", "polygon"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (TypeError, ValueError):
                pass
    return d
