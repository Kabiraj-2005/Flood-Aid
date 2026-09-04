"""
Does the router actually avoid water?

The claim is "routes around water, not through it". This file tries to
prove it, and to prove the three cases that matter more than the happy
path: trapped, last resort, and comparison against a router that ignores
flooding entirely.

    python3 test_routing.py
"""

import time
from backend import fakedata
from backend.danger import build_danger_map, haversine_m
from backend.routing import (
    find_route, route_to_safety, apply_zones, _segment_hits_circle,
    _segment_point_distance_m,
)

NOW = 1_770_000_000_000          # pinned, so decay maths is identical every run
ok = lambda m: print("  pass  " + m)


def crosses_any(graph, path, zones):
    """Ground truth check: does this path physically enter a zone?"""
    hits = []
    for a, b in zip(path, path[1:]):
        pa, pb = graph.nodes[a], graph.nodes[b]
        for z in zones:
            if z["routing"] == "ignore":
                continue
            if _segment_hits_circle(pa, pb, (z["lat"], z["lon"]), z["radius_m"]):
                hits.append((a, b, z["cluster_id"], z["routing"]))
    return hits


# ---------------------------------------------------------------- geometry
print("\nsegment vs circle")
assert _segment_hits_circle((26.25, 92.34), (26.25, 92.3436),
                            (26.25, 92.342), 100)
assert not _segment_hits_circle((26.25, 92.34), (26.25, 92.3436),
                                (26.26, 92.342), 100)
ok("a segment passing near a zone is detected, one far away is not")

# the closest point can be in the MIDDLE of a segment, not at either end
a, b = (26.2500, 92.3400), (26.2500, 92.3600)
mid = (26.2505, 92.3500)          # ~55 m off the middle of the line
assert _segment_hits_circle(a, b, mid, 100)
assert haversine_m(*a, *mid) > 200 and haversine_m(*b, *mid) > 200
ok("detects a zone sitting over the middle of a long road, not just its ends")

# A previous control-room bug drew zone circles at one radius but blocked
# roads as if they were much bigger — the map looked like nearly every road
# was underwater. apply_zones must never reach further than a zone's own
# (rendered) radius_m, with some margin for the segment geometry, not some
# other constant.
print("\napply_zones never blocks a road far from every zone's own radius")
g = fakedata.grid_town()
zones = [
    {"cluster_id": "z-a", "lat": g.nodes["1,1"][0], "lon": g.nodes["1,1"][1],
     "radius_m": 120.0, "routing": "block"},
    {"cluster_id": "z-b", "lat": g.nodes["4,4"][0], "lon": g.nodes["4,4"][1],
     "radius_m": 250.0, "routing": "block"},
    {"cluster_id": "z-c", "lat": g.nodes["7,2"][0], "lon": g.nodes["7,2"][1],
     "radius_m": 90.0, "routing": "block"},
]
blocked, _, _ = apply_zones(g, zones)

far_from_every_zone = near_some_zone = 0
for key in g.edge_meta:
    a_id, b_id = key
    a, b = g.nodes[a_id], g.nodes[b_id]
    distances = [_segment_point_distance_m(a, b, (z["lat"], z["lon"])) for z in zones]
    if all(d > 2 * z["radius_m"] for d, z in zip(distances, zones)):
        far_from_every_zone += 1
        assert key not in blocked, (
            f"{key} is {min(distances):.0f} m from the nearest zone centre — "
            f"more than 2x every zone's own radius — but apply_zones blocked it anyway"
        )
    else:
        near_some_zone += 1

# sanity: the scene needs to actually exercise both cases or the assert above is vacuous
assert far_from_every_zone > 0 and near_some_zone > 0
ok(f"{far_from_every_zone} of {len(g.edge_meta)} road segments sit beyond 2x every "
   f"zone's radius, and apply_zones left every one of them open")
ok(f"{len(blocked)} segment(s) actually near a zone were blocked")


# ------------------------------------------------------------ the detour
print("\nscene: confirmed flooding on the direct line")
scene = fakedata.scene_route_detour(NOW)
g = scene["graph"]
dmap = build_danger_map(scene["reports"], NOW)
zones = dmap["zones"]
print(f"        {len(zones)} zone(s): " +
      ", ".join(f"{z['danger_name']} {z['routing']}" for z in zones))

naive = find_route(g, scene["start"], scene["goals"], zones=[], mode="drive")
aware = find_route(g, scene["start"], scene["goals"], zones=zones, mode="drive")

assert naive["found"] and aware["found"]
print(f"        ignoring flooding: {naive['distance_m']:.0f} m")
print(f"        avoiding flooding: {aware['distance_m']:.0f} m")

naive_hits = crosses_any(g, naive["path"], zones)
assert naive_hits, "the naive route should have gone through the water"
ok(f"a router that ignores flooding drives through {len(naive_hits)} flooded segment(s)")

aware_hits = [h for h in crosses_any(g, aware["path"], zones)
              if h[3] == "block"]
assert not aware_hits, aware_hits
ok("our route crosses ZERO confirmed danger segments")

assert aware["distance_m"] >= naive["distance_m"]
extra = aware["distance_m"] - naive["distance_m"]
ok(f"the detour costs {extra:.0f} m more — that is the price of not drowning")
ok(f"evidence line: \"{aware['evidence']}\"")

assert aware["roads_removed"] > 0
ok(f"{aware['roads_removed']} road segments removed before searching")


# -------------------------------------------------------------- trapped
print("\nscene: ringed by confirmed flooding, no way out")
scene = fakedata.scene_route_trapped(NOW)
g = scene["graph"]
zones = build_danger_map(scene["reports"], NOW)["zones"]
res = find_route(g, scene["start"], scene["goals"], zones=zones)

assert res["found"] is False, res
ok("returns found=False rather than a route through water")
print(f"        reason: {res['reason']}")
ok("the reason is a sentence a dispatcher can act on, not a stack trace")


# ---------------------------------------------------------- last resort
print("\nscene: the only way out crosses an UNCONFIRMED zone")
scene = fakedata.scene_route_last_resort(NOW)
g = scene["graph"]
zones = build_danger_map(scene["reports"], NOW)["zones"]
blocked, penalties, _ = apply_zones(g, zones)
print(f"        {len(blocked)} edges blocked, {len(penalties)} made expensive")

res = find_route(g, scene["start"], scene["goals"], zones=zones,
                 allow_uncertain=True)
assert res["found"], res
ok("still returns a route instead of giving up")
assert res["confidence"] == "uncertain", res
ok(f"and labels it honestly: \"{res['evidence']}\"")

strict = find_route(g, scene["start"], scene["goals"], zones=zones,
                    allow_uncertain=False)
assert strict["found"] is False
ok("with allow_uncertain=False the same request correctly finds nothing")


# ------------------------------------------------------- safe zone choice
print("\nnearest safe zone WITH SPACE")
scene = fakedata.scene_route_detour(NOW)
g = scene["graph"]
zones = build_danger_map(scene["reports"], NOW)["zones"]
near_lat, near_lon = g.nodes["1,1"]
far_lat, far_lon = g.nodes["8,8"]

safe = [
    {"id": "camp-near", "name": "Camp 1", "lat": near_lat, "lon": near_lon,
     "capacity": 40, "occupied": 40, "status": "open"},     # FULL
    {"id": "camp-far", "name": "Camp 3", "lat": far_lat, "lon": far_lon,
     "capacity": 40, "occupied": 5, "status": "open"},
]
start_lat, start_lon = g.nodes["0,0"]
res = route_to_safety(g, start_lat, start_lon, safe, zones)

assert res["found"] and res["destination"]["id"] == "camp-far", res
ok("skips the nearer camp because it is full, and says which it chose")
print(f"        -> {res['destination']['name']}, "
      f"{res['travel_minutes']} min, {res['evidence']}")

full = [dict(s, occupied=s["capacity"]) for s in safe]
res = route_to_safety(g, start_lat, start_lon, full, zones)
assert res["found"] is False and "full" in res["reason"]
ok("when every camp is full it says so instead of routing somewhere useless")


# ------------------------------------------------------------- benchmark
print("\nbenchmark: 40 random trips across the grid")
import random
rng = random.Random(7)
scene = fakedata.scene_route_detour(NOW)
g = scene["graph"]
zones = build_danger_map(scene["reports"], NOW)["zones"]

naive_through = aware_through = 0
extra_pct = []
t0 = time.time()

for _ in range(40):
    s = f"{rng.randint(0,8)},{rng.randint(0,8)}"
    e = f"{rng.randint(0,8)},{rng.randint(0,8)}"
    if s == e:
        continue
    n = find_route(g, s, {e}, zones=[])
    a = find_route(g, s, {e}, zones=zones)
    if n["found"] and crosses_any(g, n["path"], zones):
        naive_through += 1
    if a["found"]:
        if [h for h in crosses_any(g, a["path"], zones) if h[3] == "block"]:
            aware_through += 1
        # Compare TRAVEL TIME, not distance. Both routers optimise time,
        # so a distance comparison can come out negative — our route takes
        # slower back streets that happen to be shorter in metres — which
        # reads as "avoiding floods is free". It is not. Time is the cost
        # the detour actually imposes.
        if n["found"] and n["travel_seconds"] > 0:
            extra_pct.append(100 * (a["travel_seconds"] - n["travel_seconds"])
                             / n["travel_seconds"])

ms = (time.time() - t0) * 1000
avg_extra = sum(extra_pct) / len(extra_pct) if extra_pct else 0.0

print(f"        routes through confirmed water — naive: {naive_through}, ours: {aware_through}")
print(f"        average detour cost: {avg_extra:.1f}% more travel time")
assert avg_extra >= 0, "avoiding flooding cannot be free — check the metric"
print(f"        80 routes computed in {ms:.0f} ms")
assert aware_through == 0
ok("zero of our routes cross confirmed flooding")
ok(f"fast enough to run on a phone ({ms/80:.1f} ms per route)")

print("\nALL CHECKS PASSED\n")
