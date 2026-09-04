"""
Fetch the OpenStreetMap road network for Morigaon district, Assam, and save
it to data/morigaon_roads.json.

This is a one-time (or occasional, re-run-when-you-want-fresher-data)
developer step, NOT something the app calls at runtime. During a flood
there may be no network at all, and a demo must never depend on an
external API being reachable — see CLAUDE.md, "works with the network
off". backend/roadloader.py reads the committed JSON file; nothing in the
app talks to Overpass.

    python3 scripts/fetch_roads.py

Only these highway types are kept — the ones a vehicle or an evacuating
family would actually use. footway/cycleway/path/service are excluded on
purpose; they inflate the node count without adding a road worth routing
onto.

    motorway, trunk, primary, secondary, tertiary, unclassified,
    residential, track

The `highway` tag is preserved on every way, since backend/roadloader.py
maps it onto routing.py's road_type (which travel speed depends on).

Overpass has no radius/node-count parameter, so "narrow the bounding box
until it fits" is done by trial: fetch, count nodes, and if the count is
over NODE_BUDGET, shrink the box around its centre and fetch again.
"""

import json
import sys
import time
from pathlib import Path

import httpx

# Centre of Morigaon town, Assam — same point backend/fakedata.py's
# BASE_LAT/BASE_LON uses for the synthetic demo grid, so real incidents
# generated around that point land inside this road network too.
CENTRE_LAT, CENTRE_LON = 26.2500, 92.3400

# District-scale extent (Morigaon district's own OSM boundary, relation
# 2025921, is roughly 50 km x 59 km and returns ~138k nodes — comfortably
# over budget). Start at a town-scale half-width and shrink from there.
START_HALF_WIDTH_KM = 13.0
SHRINK_FACTOR = 0.8
MIN_HALF_WIDTH_KM = 1.0
MAX_ATTEMPTS = 8

NODE_BUDGET = 30_000

HIGHWAY_TYPES = [
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "track",
]

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "morigaon_roads.json"

M_PER_DEG_LAT = 111_320.0


def bbox_for(centre_lat, centre_lon, half_width_km):
    """(south, west, north, east) for a roughly square box half_width_km
    out from the centre in every direction."""
    import math
    half_width_m = half_width_km * 1000.0
    dlat = half_width_m / M_PER_DEG_LAT
    dlon = half_width_m / (M_PER_DEG_LAT * math.cos(math.radians(centre_lat)))
    return (
        centre_lat - dlat, centre_lon - dlon,
        centre_lat + dlat, centre_lon + dlon,
    )


def build_query(bbox):
    south, west, north, east = bbox
    highway_re = "^(" + "|".join(HIGHWAY_TYPES) + ")$"
    return f"""
[out:json][timeout:90];
(
  way["highway"~"{highway_re}"]({south},{west},{north},{east});
);
out body;
>;
out skel qt;
""".strip()


HEADERS = {
    "User-Agent": "FloodAid-fetch-roads/1.0 (github.com/anthropics; contact: ukabiraj48@gmail.com)",
    "Accept": "*/*",
}


def fetch(bbox, attempt):
    query = build_query(bbox)
    print(f"  attempt {attempt}: bbox={tuple(round(v, 4) for v in bbox)}", file=sys.stderr)
    with httpx.Client(timeout=120.0, headers=HEADERS) as client:
        r = client.post(OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        return r.json()


def counts(osm_json):
    nodes = sum(1 for e in osm_json["elements"] if e["type"] == "node")
    ways = sum(1 for e in osm_json["elements"] if e["type"] == "way")
    return nodes, ways


def main():
    half_width = START_HALF_WIDTH_KM
    result = None
    n_nodes = n_ways = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        bbox = bbox_for(CENTRE_LAT, CENTRE_LON, half_width)
        try:
            result = fetch(bbox, attempt)
        except httpx.HTTPError as e:
            print(f"Overpass request failed: {e}", file=sys.stderr)
            sys.exit(1)

        n_nodes, n_ways = counts(result)
        print(f"    -> {n_nodes} nodes, {n_ways} ways "
              f"(half-width {half_width:.2f} km)", file=sys.stderr)

        if n_nodes <= NODE_BUDGET:
            break
        if half_width <= MIN_HALF_WIDTH_KM:
            print("  hit MIN_HALF_WIDTH_KM and still over budget — "
                  "keeping this result anyway", file=sys.stderr)
            break

        half_width = max(half_width * SHRINK_FACTOR, MIN_HALF_WIDTH_KM)
        time.sleep(2)   # be polite to the shared public Overpass instance
    else:
        print("  ran out of attempts without fitting the node budget — "
              "keeping the last result", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(result, f)

    edge_estimate = sum(
        max(0, len(e.get("nodes", [])) - 1)
        for e in result["elements"] if e["type"] == "way"
    )
    print(f"\nsaved {OUT_PATH}")
    print(f"nodes: {n_nodes}")
    print(f"ways:  {n_ways}")
    print(f"edges (way segments, before connectivity trimming): {edge_estimate}")


if __name__ == "__main__":
    main()
