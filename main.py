"""
FloodAid backend — the thin path.

Three endpoints matter right now:
  POST /api/reports  -> accept a batch from a phone's outbox. Idempotent.
  GET  /api/changes  -> everything that changed since a timestamp (delta sync).
  GET  /api/reports  -> the control room list.

Run:  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

import json
from typing import Optional, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from . import db
from .severity import compute_severity

app = FastAPI(title="FloodAid")

# Create tables at import time so tests and workers never race the startup hook.
db.init()

# The phone may be served from anywhere during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- models

class ReportIn(BaseModel):
    # identity — generated ON THE PHONE
    id: str
    device_id: str
    counter: int = 0
    phone_time: int

    source: str = "volunteer"
    text: str = ""
    photo_ids: List[str] = []

    lat: Optional[float] = None
    lon: Optional[float] = None
    polygon: Optional[list] = None
    location_confidence: float = 1.0

    people_count: Optional[int] = None
    injured: int = 0
    children_elderly: int = 0
    water_level: Optional[str] = None
    rising: int = 0
    road_passable: str = "unknown"

    # Which fields this device actually edited. Empty means "all of them"
    # (a brand new report). On an EDIT the phone must name the fields it
    # touched, otherwise we cannot tell an untouched field from one that was
    # deliberately set back to its old value — and one phone's stale copy
    # silently undoes another phone's fix.
    changed: List[str] = []


class SyncIn(BaseModel):
    reports: List[ReportIn] = []
    last_cursor: int = 0          # updated_at of the newest row the phone has


# ------------------------------------------------------- merge behaviour

# Fields a phone is allowed to set. Anything else is server-owned.
CLIENT_FIELDS = [
    "source", "text", "photo_ids", "lat", "lon", "polygon",
    "location_confidence", "people_count", "injured", "children_elderly",
    "water_level", "rising", "road_passable",
]


def _serialise(value):
    return json.dumps(value) if isinstance(value, (list, dict)) else value


def upsert_report(conn, r: ReportIn) -> str:
    """
    Insert, or merge into an existing row.

    Merge rule: FIELD BY FIELD, higher counter wins.
    If two volunteers edited different fields offline, we keep both changes.
    Phone clocks are not trusted, which is why `counter` exists.

    Returns "created" | "merged" | "ignored".
    """
    ts = db.now_ms()
    existing = conn.execute(
        "SELECT * FROM reports WHERE id = ?", (r.id,)
    ).fetchone()

    if existing is None:
        cols = ["id", "device_id", "counter", "phone_time"] + CLIENT_FIELDS
        vals = [r.id, r.device_id, r.counter, r.phone_time] + [
            _serialise(getattr(r, f)) for f in CLIENT_FIELDS
        ]
        cols += ["reported_at", "synced_at", "updated_at"]
        vals += [r.phone_time, ts, ts]

        conn.execute(
            f"INSERT INTO reports ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            vals,
        )
        return "created"

    # Already seen this exact version — a retry. Do nothing, say nothing.
    if r.counter <= existing["counter"]:
        return "ignored"

    touched = r.changed or CLIENT_FIELDS
    changed = {}
    for f in CLIENT_FIELDS:
        if f not in touched:
            continue                      # this device did not edit the field
        incoming = getattr(r, f)
        if incoming is None:
            continue
        changed[f] = _serialise(incoming)

    if not changed:
        return "ignored"

    changed["counter"] = r.counter
    changed["updated_at"] = ts
    changed["synced_at"] = ts

    sets = ", ".join(f"{k} = ?" for k in changed)
    conn.execute(
        f"UPDATE reports SET {sets} WHERE id = ?",
        list(changed.values()) + [r.id],
    )
    return "merged"


# ------------------------------------------------------------ endpoints

@app.post("/api/reports")
def receive_reports(payload: SyncIn):
    """
    A phone empties its outbox here.

    Safe to call with the same reports many times — that is the whole point.
    Returns the server's changes since last_cursor so one round trip syncs
    both directions.
    """
    conn = db.connect()
    results = {"created": 0, "merged": 0, "ignored": 0}

    for r in payload.reports:
        outcome = upsert_report(conn, r)
        results[outcome] += 1

    conn.commit()

    # Recompute severity for anything that moved.
    for row in conn.execute(
        "SELECT * FROM reports WHERE updated_at >= ?", (payload.last_cursor,)
    ).fetchall():
        sev = compute_severity(db.row_to_dict(row))
        conn.execute(
            "UPDATE reports SET severity = ? WHERE id = ?", (sev, row["id"])
        )
    conn.commit()

    changes = conn.execute(
        "SELECT * FROM reports WHERE updated_at > ? ORDER BY updated_at",
        (payload.last_cursor,),
    ).fetchall()

    cursor = max([c["updated_at"] for c in changes], default=payload.last_cursor)
    out = {
        "accepted": results,
        "changes": [db.row_to_dict(c) for c in changes],
        "cursor": cursor,
    }
    conn.close()
    return out


@app.get("/api/changes")
def get_changes(since: int = 0):
    """Pull-only sync, for a phone with nothing to send."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM reports WHERE updated_at > ? ORDER BY updated_at",
        (since,),
    ).fetchall()
    cursor = max([r["updated_at"] for r in rows], default=since)
    conn.close()
    return {"changes": [db.row_to_dict(r) for r in rows], "cursor": cursor}


@app.get("/api/reports")
def list_reports():
    """Control room list — worst and longest-waiting first."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY severity DESC, reported_at ASC"
    ).fetchall()
    conn.close()
    return {"reports": [db.row_to_dict(r) for r in rows]}


@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now_ms()}


# Serve the phone app from the same origin so it works on a LAN.
WEB = Path(__file__).parent.parent / "web"
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
