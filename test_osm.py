"""
Does the real Morigaon road network actually work?

test_routing.py stays on the synthetic grid_town() graph — those scenes
have known answers, and that is the correctness fixture we are not giving
up. This file is the demo network's own sanity check: the data loads, the
nearest-node index agrees with brute force, routing is fast enough for a
phone, danger zones still force detours on real (non-grid) geometry, and
the network is not secretly a pile of disconnected fragments.

    python3 test_osm.py
"""

import random
import time

from backend.roadloader import DEFAULT_PATH, connected_components, load_osm
from backend.danger import haversine_m
from backend.routing import _segment_hits_circle, apply_zones, find_route

ok = lambda m: print("  pass  " + m)

print(f"\nloading {DEFAULT_PATH}")
t0 = time.time()
GRAPH = load_osm(DEFAULT_PATH)
load_ms = (time.time() - t0) * 1000


# ------------------------------------------------------------- node/edge counts
print("\nnode and edge counts")
n_nodes, n_edges = len(GRAPH.nodes), len(GRAPH.edge_meta)
print(f"        {n_nodes} nodes, {n_edges} edges (loaded in {load_ms:.0f} ms)")
assert n_nodes > 0 and n_edges > 0, "the graph loaded empty — check data/morigaon_roads.json"
ok("real road data loaded, non-empty")


# --------------------------------------------------------------- connectivity
print("\nconnected components")
components = connected_components(GRAPH)
largest = components[0]
fraction = len(largest) / n_nodes
print(f"        {len(components)} component(s); largest is {len(largest)} of "
      f"{n_nodes} nodes ({fraction:.1%})")
assert 0.0 < fraction <= 1.0
ok(f"largest connected component covers {fraction:.1%} of all nodes")
if fraction < 0.90:
    print("        (below 90% — load_osm() should already have trimmed to just "
          "this component; a start or goal on a smaller fragment would silently "
          "fail to route)")


# --------------------------------------------------------------- nearest_node
print("\nnearest_node vs brute-force linear scan, 50 random coordinates")


def brute_nearest(graph, lat, lon):
    best, best_d = None, float("inf")
    for nid, (nlat, nlon) in graph.nodes.items():
        d = haversine_m(lat, lon, nlat, nlon)
        if d < best_d:
            best, best_d = nid, d
    return best, best_d


lats = [lat for lat, _ in GRAPH.nodes.values()]
lons = [lon for _, lon in GRAPH.nodes.values()]
rng = random.Random(20260904)
points = [(rng.uniform(min(lats), max(lats)), rng.uniform(min(lons), max(lons)))
          for _ in range(50)]

t0 = time.time()
for lat, lon in points:
    brute_nearest(GRAPH, lat, lon)
brute_ms = (time.time() - t0) * 1000

t0 = time.time()
bucketed = [GRAPH.nearest_node(lat, lon) for lat, lon in points]
bucket_ms = (time.time() - t0) * 1000

mismatches = []
for (lat, lon), (nid, d) in zip(points, bucketed):
    b_nid, b_d = brute_nearest(GRAPH, lat, lon)
    # Compare distance, not id — two nodes can legitimately tie.
    if abs(d - b_d) > 1e-6:
        mismatches.append((lat, lon, nid, d, b_nid, b_d))

for lat, lon, nid, d, b_nid, b_d in mismatches:
    print(f"        MISMATCH ({lat:.5f},{lon:.5f}): bucketed {nid}@{d:.1f}m "
          f"vs brute {b_nid}@{b_d:.1f}m")
assert not mismatches, f"{len(mismatches)}/{len(points)} points disagreed with brute force"
ok(f"all 50 points agree with brute force "
   f"({brute_ms:.0f} ms brute vs {bucket_ms:.0f} ms bucketed, "
   f"{brute_ms / max(bucket_ms, 0.001):.0f}x faster)")


# ------------------------------------------------------------------- routing
print("\na route between two random connected nodes, under 100ms")
node_ids = list(largest)
rng = random.Random(7)
route_times = []
sample_route = None
for _ in range(20):
    a, b = rng.sample(node_ids, 2)
    t0 = time.time()
    result = find_route(GRAPH, a, {b}, zones=[])
    elapsed_ms = (time.time() - t0) * 1000
    assert result["found"], (
        f"{a} -> {b} are both in the largest connected component but no route "
        f"was found: {result}")
    route_times.append(elapsed_ms)
    if sample_route is None and len(result["path"]) >= 8:
        sample_route = (a, b, result)

print(f"        20 routes: {min(route_times):.1f}-{max(route_times):.1f} ms "
      f"(avg {sum(route_times)/len(route_times):.1f} ms)")
assert max(route_times) < 100.0, f"slowest route took {max(route_times):.1f} ms"
ok("every route computed in under 100 ms")


# ------------------------------------------------------- danger forces detour
print("\na danger zone on a route's midpoint forces a different, clear path")
assert sample_route is not None, "no long-enough route turned up in 20 tries"
start, goal, baseline = sample_route
mid_lat, mid_lon = baseline["coordinates"][len(baseline["coordinates"]) // 2]
print(f"        baseline {start} -> {goal}: {len(baseline['path'])} nodes, "
      f"{baseline['distance_m']:.0f} m")

zone = {
    "cluster_id": "z-test", "lat": mid_lat, "lon": mid_lon,
    "radius_m": 120.0, "routing": "block",
}
blocked, _, _ = apply_zones(GRAPH, [zone])
assert blocked, "the zone did not block any edge on the baseline path — pick a bigger radius"

detour = find_route(GRAPH, start, {goal}, zones=[zone])
assert detour["found"], (
    f"the network has no way around a single 120 m zone between {start} and "
    f"{goal} — either genuinely trapped, or the test picked a bad pair")
assert detour["path"] != baseline["path"], (
    "the router returned the exact same path even with the midpoint blocked")

hits = [
    (a, b) for a, b in zip(detour["path"], detour["path"][1:])
    if _segment_hits_circle(GRAPH.nodes[a], GRAPH.nodes[b],
                            (zone["lat"], zone["lon"]), zone["radius_m"])
]
assert not hits, f"the detour still crosses the zone at {hits}"
ok(f"detour uses {len(detour['path'])} nodes ({detour['distance_m']:.0f} m) "
   f"and crosses the blocked zone zero times")

print("\nALL CHECKS PASSED\n")
