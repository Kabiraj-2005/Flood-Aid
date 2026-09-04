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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from backend import db, fakedata

# id, name, north_m/east_m offset from BASE_LAT/BASE_LON, capacity, occupied
SAFE_ZONES = [
    ("sz-1", "Relief Camp — Ward 3", -300, -300, 150, 40),
    ("sz-2", "School Shelter — Ward 5", 1400, 1200, 200, 60),
    ("sz-3", "Relief Camp — Ward 9", -1200, 1600, 100, 100),  # deliberately full
]


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
    ap.add_argument("--n", type=int, default=240, help="number of reports")
    ap.add_argument("--incidents", type=int, default=12, help="hidden true incidents")
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

    scene = fakedata.scene_realistic(
        n=args.n, incidents=args.incidents, seed=args.seed, accuracy=args.accuracy)

    try:
        created, merged, ignored = post_reports(args.url, scene["reports"])
    except httpx.ConnectError:
        print(f"could not reach {args.url} — is the server running?\n"
              f"  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    print(f"posted {len(scene['reports'])} reports to {args.url}: "
          f"{created} created, {merged} merged, {ignored} ignored")
    print(f"open {args.url}/control.html")


if __name__ == "__main__":
    main()
