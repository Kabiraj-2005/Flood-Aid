"""
Seed a running FloodAid server with a realistic demo scene, so the control
room screen (web/control.html) has content to show on load.

Posts backend.fakedata.scene_realistic()'s reports through the real
POST /api/reports endpoint, exactly like a fleet of phones syncing their
outboxes — so the same merge / idempotency / severity path the app uses in
production is what fills the demo, not a database shortcut.

Safe zones have no POST endpoint (the control room only ever reads what
/api/route decides; it doesn't manage shelters), so those go straight into
the database instead. That is local operator setup, not something a phone
or the control room does over the network, so it does not belong behind an
HTTP call.

    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000   # one terminal
    python3 scripts/seed_demo.py                                   # another
    open http://localhost:8000/control.html
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from backend import db, fakedata
from backend.danger import CLUSTER_RADIUS_M, haversine_m
from backend.routing import apply_zones, zones_touching_roads

# id, name, north_m/east_m offset from BASE_LAT/BASE_LON, capacity, occupied
SAFE_ZONES = [
    ("sz-1", "Relief Camp — Ward 3", -300, -300, 150, 40),
    ("sz-2", "School Shelter — Ward 5", 1400, 1200, 200, 60),
    ("sz-3", "Relief Camp — Ward 9", -1200, 1600, 100, 100),  # deliberately full
]


def road_graph():
    """The same synthetic grid backend.main._road_graph() builds for /api/route.

    There is no endpoint to fetch the live graph, so this must be called the
    same way, with the same defaults, or the demo's zones and the router's
    roads drift into different places again.
    """
    return fakedata.grid_town()


def pick_incident_centres(graph, count, seed):
    """Incident centres that sit ON the road network, not scattered near it.

    grid_town() covers a small, fixed area (about 1.6 km square by
    default). scene_realistic()'s own centre-picker scatters incidents over
    roughly +/-6 km around the same base point regardless of what road
    network is in play, so the two barely ever overlap — no danger zone
    intersects any road, and the routing demo has nothing to route around.

    Picking real graph nodes and jittering by a few metres keeps each
    incident's cluster (spread up to ~75 m, see scene_realistic) centred
    close enough to the node that its drawn zone (spread + CLUSTER_RADIUS_M,
    at least 150 m) reliably reaches every road edge meeting there.

    Centres are kept at least MIN_SEPARATION_M apart so incidents stay
    distinct zones instead of single-link-chaining into one giant cluster
    that swallows most of the small grid's roads.
    """
    MIN_SEPARATION_M = 2.0 * CLUSTER_RADIUS_M + 150.0   # clear of chaining, with margin
    node_ids = list(graph.nodes.keys())
    if count > len(node_ids):
        raise ValueError(
            f"asked for {count} incidents but the road network only has "
            f"{len(node_ids)} nodes to place them on")
    rng = random.Random(seed)

    chosen = None
    for _ in range(500):    # greedy packing is order-sensitive; retry with new shuffles
        shuffled = node_ids[:]
        rng.shuffle(shuffled)
        candidate = []
        for nid in shuffled:
            lat, lon = graph.nodes[nid]
            if all(haversine_m(lat, lon, *graph.nodes[c]) >= MIN_SEPARATION_M
                   for c in candidate):
                candidate.append(nid)
            if len(candidate) == count:
                break
        if len(candidate) == count:
            chosen = candidate
            break
    if chosen is None:
        raise ValueError(
            f"could not find {count} road nodes at least {MIN_SEPARATION_M:.0f} m "
            f"apart on this grid — ask for fewer incidents or a bigger grid")

    return [fakedata.offset(*graph.nodes[nid], rng.uniform(-30, 30), rng.uniform(-30, 30))
            for nid in chosen]


def verify_zones_on_roads(graph, zones):
    """Fail loudly if the seeded scene doesn't demonstrate anything.

    A route that never crosses a danger zone proves nothing about
    danger-aware routing. At least half of the confirmed (routing=="block")
    zones must actually intersect a road edge, or this is the same
    coordinate-space bug again, silently back.
    """
    confirmed = [z for z in zones if z["routing"] == "block"]
    touching = zones_touching_roads(graph, confirmed)
    blocked, penalties, _ = apply_zones(graph, zones)

    print(f"{len(confirmed)} confirmed danger zone(s), {len(touching)} of them "
          f"touch the road network")
    print(f"{len(blocked)} of {len(graph.edge_meta)} roads removed by confirmed "
          f"flooding, {len(penalties)} more made expensive by unconfirmed zones")

    assert confirmed, (
        "no confirmed danger zones were generated — nothing for the router "
        "to avoid, the demo would prove nothing")
    assert len(touching) >= len(confirmed) / 2, (
        f"only {len(touching)}/{len(confirmed)} confirmed zones intersect a "
        f"road — seed incidents and the road network are in different places "
        f"again")


def seed_safe_zones():
    conn = db.connect()
    for zid, name, north_m, east_m, capacity, occupied in SAFE_ZONES:
        lat, lon = fakedata.offset(fakedata.BASE_LAT, fakedata.BASE_LON, north_m, east_m)
        status = "full" if occupied >= capacity else "open"
        conn.execute(
            "INSERT OR REPLACE INTO safe_zones "
            "(id, name, lat, lon, capacity, occupied, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (zid, name, lat, lon, capacity, occupied, status),
        )
    conn.commit()
    conn.close()
    print(f"seeded {len(SAFE_ZONES)} safe zones")


def post_reports(base_url, reports, batch_size=40):
    created = merged = ignored = 0
    with httpx.Client(timeout=10.0) as client:
        for i in range(0, len(reports), batch_size):
            batch = reports[i:i + batch_size]
            r = client.post(f"{base_url}/api/reports",
                             json={"reports": batch, "last_cursor": 0})
            r.raise_for_status()
            out = r.json()["accepted"]
            created += out["created"]
            merged += out["merged"]
            ignored += out["ignored"]
    return created, merged, ignored


def main():
    ap = argparse.ArgumentParser(
        description="Seed a running FloodAid server with a demo scene.")
    ap.add_argument("--url", default="http://localhost:8000",
                     help="base URL of the running server")
    ap.add_argument("--n", type=int, default=120, help="number of reports")
    ap.add_argument("--incidents", type=int, default=5,
                     help="hidden true incidents (kept low: grid_town's default "
                          "grid is only ~1.6 km square, and each zone typically "
                          "covers 200-300 m — too many incidents flood every road "
                          "on it and there's nothing left to route around)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--accuracy", type=float, default=0.82,
                     help="probability an observation matches the hidden truth")
    ap.add_argument("--reset", action="store_true",
                     help="wipe existing reports before seeding, for a clean demo")
    args = ap.parse_args()

    if args.reset:
        conn = db.connect()
        conn.execute("DELETE FROM reports")
        conn.commit()
        conn.close()
        print("cleared existing reports")

    seed_safe_zones()

    graph = road_graph()
    centres = pick_incident_centres(graph, args.incidents, seed=args.seed)
    scene = fakedata.scene_realistic(
        n=args.n, incidents=args.incidents, seed=args.seed, accuracy=args.accuracy,
        centres=centres)

    try:
        created, merged, ignored = post_reports(args.url, scene["reports"])
    except httpx.ConnectError:
        print(f"could not reach {args.url} — is the server running?\n"
              f"  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    print(f"posted {len(scene['reports'])} reports to {args.url}: "
          f"{created} created, {merged} merged, {ignored} ignored")

    with httpx.Client(timeout=10.0) as client:
        live_danger = client.get(f"{args.url}/api/danger").json()
    verify_zones_on_roads(graph, live_danger["zones"])

    print(f"open {args.url}/control.html")


if __name__ == "__main__":
    main()
