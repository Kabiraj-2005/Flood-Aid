"""
FloodAid backend — the thin path.

Three endpoints matter right now:
  POST /api/reports  -> accept a batch from a phone's outbox. Idempotent.
  GET  /api/changes  -> everything that changed since a timestamp (delta sync).
  GET  /api/reports  -> the control room list.

Run:  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

import json
import random
from typing import Optional, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

from . import db
from .severity import compute_severity, explain
from .danger import build_danger_map
from .routing import route_to_safety, apply_zones

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


@app.get("/api/danger")
def danger_map():
    """
    The live danger map, built fresh from every report.

    Rebuilt on each call rather than cached, because confidence decays with
    the clock — a cached map is wrong the moment it is stored. At district
    scale this takes about 15 ms, so caching would be a premature
    optimisation that introduces staleness bugs for no gain.
    """
    conn = db.connect()
    rows = conn.execute("SELECT * FROM reports").fetchall()
    conn.close()
    return build_danger_map([db.row_to_dict(r) for r in rows])


@app.get("/api/reports/{report_id}/why")
def why(report_id: str):
    """The severity breakdown, for the line shown next to the score."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    if row is None:
        return {"error": "not found"}
    r = db.row_to_dict(row)
    return {"severity": compute_severity(r), "because": explain(r)}


@app.get("/api/route")
def route(lat: float, lon: float, mode: str = "drive"):
    """
    Route from a position to the nearest safe zone that still has space.

    NOTE: this endpoint exists for the control room. On the phone the same
    search runs locally against the bundled road graph, because during a
    flood there may be nothing to call. Server and device must give the
    same answer — keep the logic in routing.py, not here.
    """
    conn = db.connect()
    reports = [db.row_to_dict(r) for r in
               conn.execute("SELECT * FROM reports").fetchall()]
    zones_rows = conn.execute("SELECT * FROM safe_zones").fetchall()
    conn.close()

    graph = _road_graph()
    if graph is None:
        return {"found": False, "reason": "no road network loaded"}

    danger = build_danger_map(reports)["zones"]
    safe = [dict(z) for z in zones_rows]
    result = route_to_safety(graph, lat, lon, safe, danger, mode)
    result["danger_zones_considered"] = len(danger)
    return result


@app.get("/api/route/demo")
def demo_route(mode: str = "drive"):
    """
    Pick a start point whose route to the nearest safe zone with space is
    forced to detour around a confirmed danger zone, then route from there.

    Exists for the control room's "find a demo route" button. At district
    scale, clicking around a 20 km map hoping to land somewhere a dozen
    small zones actually affect is not a demo, it's luck — and the whole
    point of this screen is showing the detour, reliably.

    Candidates are one endpoint of every currently-blocked road edge: each
    is, by construction, immediately next to flooding the router has to
    route around. For each, check whether the ROUTE THAT IGNORES DANGER
    (zones=[]) would actually cross a blocked edge on its way to the
    nearest safe zone — if it does, the danger-aware route from that same
    point is guaranteed to differ, no need to compute it just to check.

    That guarantee matters for latency, not just for tidiness:
    apply_zones() over the full danger map costs ~225ms on this graph (12
    zones x 25k edges), so route_to_safety(..., zones=danger, ...) pays
    that on every call. Calling it once per candidate — the first version
    of this endpoint did — meant up to 60 candidates x that cost, and a
    button click that could take north of ten seconds. blocked (below) is
    computed exactly once; membership-testing a candidate's naive path
    against that set is nearly free, and the real (danger-aware) route is
    computed only once, for the candidate that already proved it needs it.
    """
    conn = db.connect()
    reports = [db.row_to_dict(r) for r in
               conn.execute("SELECT * FROM reports").fetchall()]
    zones_rows = conn.execute("SELECT * FROM safe_zones").fetchall()
    conn.close()

    graph = _road_graph()
    if graph is None:
        return {"found": False, "reason": "no road network loaded"}

    danger = build_danger_map(reports)["zones"]
    safe = [dict(z) for z in zones_rows]

    zone_effects = apply_zones(graph, danger)
    blocked, _penalties, _why = zone_effects
    if not blocked:
        return {"found": False,
                "reason": "no roads are currently blocked — nothing to detour around"}

    candidates = [nid for pair in blocked for nid in pair]
    random.shuffle(candidates)

    tried = set()
    for node_id in candidates:
        if node_id in tried:
            continue
        tried.add(node_id)
        if len(tried) > 60:      # bound worst-case latency for an interactive button
            break

        lat, lon = graph.nodes[node_id]
        naive = route_to_safety(graph, lat, lon, safe, zones=[], mode=mode)
        if not naive.get("found"):
            continue

        path_edges = {tuple(sorted((a, b)))
                      for a, b in zip(naive["path"], naive["path"][1:])}
        if not (path_edges & blocked):
            continue     # this start's shortest route never needed a blocked road anyway

        # zone_effects reused here (and would be for every other candidate
        # that reaches this point) instead of recomputed — see find_route's
        # _zone_effects docstring for why that recomputation was the whole
        # latency problem.
        aware = route_to_safety(graph, lat, lon, safe, zones=danger, mode=mode,
                                _zone_effects=zone_effects)
        if aware.get("found"):
            aware["danger_zones_considered"] = len(danger)
            aware["demo_start"] = {"lat": lat, "lon": lon}
            aware["naive_distance_m"] = naive["distance_m"]
            return aware

    return {
        "found": False,
        "reason": f"checked {len(tried)} blocked-road neighbourhood(s) but none forced "
                  f"a detour to the nearest safe zone with space — try again, or after "
                  f"the danger map next changes",
    }


_GRAPH = None


def _road_graph():
    """
    The road network the app actually routes on.

    test_routing.py keeps testing against the synthetic grid_town() graph
    directly — those scenes have known answers, and that stays the
    correctness fixture. This is the demo network: real Morigaon roads
    (OpenStreetMap, fetched offline by scripts/fetch_roads.py — see that
    script's docstring for why this is never fetched at runtime), loaded
    once and cached for the life of the process.
    """
    global _GRAPH
    if _GRAPH is None:
        from .roadloader import load_osm, DEFAULT_PATH
        _GRAPH = load_osm(DEFAULT_PATH)
    return _GRAPH


@app.get("/api/roads")
def roads():
    """
    The road network the router actually runs on: nodes and edges only.

    control.html used to keep its own hardcoded copy of grid_town() to draw
    the map. That drifts the moment either copy changes, and shows routes
    that appear to leave the road network. This is the same graph
    _road_graph() builds, so the map always matches what /api/route uses.

    Split from /api/roads/blocked (see below) because at OSM scale this
    payload is tens of thousands of nodes — the control room fetches this
    once on load, not on every 5s poll, since the graph itself never
    changes while the server is up.
    """
    graph = _road_graph()
    if graph is None:
        return {"nodes": {}, "edges": []}
    return {
        "nodes": {nid: [lat, lon] for nid, (lat, lon) in graph.nodes.items()},
        "edges": [[a, b] for (a, b) in graph.edge_meta.keys()],
    }


@app.get("/api/roads/blocked")
def roads_blocked():
    """
    Which road edges the CURRENT danger map removes or penalises.

    Split out from /api/roads so the control room can poll just this —
    small, and genuinely changes every few seconds — without re-sending the
    whole (potentially tens-of-thousands-of-nodes) graph on every cycle.

    Comes from apply_zones() — the same function find_route() calls —
    instead of the map re-deriving it client-side. A second, JS copy of the
    zone-vs-edge geometry would drift from routing.py the moment either one
    changed, and the map would show a road as open that the router has
    already removed.
    """
    graph = _road_graph()
    if graph is None:
        return {"blocked": [], "penalised": []}

    conn = db.connect()
    reports = [db.row_to_dict(r) for r in
               conn.execute("SELECT * FROM reports").fetchall()]
    conn.close()
    danger = build_danger_map(reports)["zones"]
    blocked, penalties, _why = apply_zones(graph, danger)

    return {
        "blocked": [[a, b] for (a, b) in blocked],
        "penalised": [[a, b] for (a, b) in penalties.keys()],
    }


@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now_ms()}


# Serve the phone app from the same origin so it works on a LAN.
WEB = Path(__file__).parent.parent / "web"
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
