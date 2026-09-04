"""
Fake data with known answers hidden inside.

This is C's first job and it must exist BEFORE the thing it measures.
Without it we cannot tell whether the clustering works or merely looks
plausible on a screen.

Every generated scene carries a `truth` block saying what the right answer
is. Then we score ourselves honestly instead of guessing.

    python3 -m backend.fakedata          # print a scene
"""

import random
import time

# Somewhere in Morigaon district, Assam. Any real coordinates would do —
# what matters is that distances are realistic.
BASE_LAT, BASE_LON = 26.2500, 92.3400

WATER_LEVELS = ["ankle", "knee", "waist", "above"]

ASSAMESE_SNIPPETS = [
    "পানী বাঢ়ি আছে",
    "বাট বন্ধ হৈ গৈছে",
    "চাৰিটা ঘৰ পানীৰ তলত",
    "মানুহ ছাদত আছে",
]
MIXED_SNIPPETS = [
    "water rising fast near school",
    "4 ghor pani niche, 2 lora ase",
    "road cut off, need boat",
    "6 log chat pe hai",
]


def offset(lat, lon, north_m, east_m):
    """Move a point by a number of metres. Good enough at this latitude."""
    return (lat + north_m / 111_320.0,
            lon + east_m / (111_320.0 * 0.9))


def make_report(rid, lat, lon, *, device, water, minutes_ago,
                source="volunteer", people=None, injured=0, rising=0,
                road="unknown", loc_conf=1.0, now=None):
    now = now or int(time.time() * 1000)
    t = now - minutes_ago * 60_000
    return {
        "id": rid,
        "device_id": device,
        "counter": 1,
        "phone_time": t,
        "source": source,
        "text": random.choice(ASSAMESE_SNIPPETS + MIXED_SNIPPETS),
        "photo_ids": [],
        "lat": lat, "lon": lon, "polygon": None,
        "location_confidence": loc_conf,
        "people_count": people if people is not None else random.randint(2, 20),
        "injured": injured,
        "children_elderly": random.choice([0, 0, 1]),
        "water_level": water,
        "rising": rising,
        "road_passable": road,
        "extraction_confidence": 0.0,
        "severity": 0.0,
        "status": "new",
        "reported_at": t,
        "synced_at": t,
        "updated_at": t,
    }


def scene_basic(now=None):
    """
    Four separate places, known in advance.

      A: 4 reports from 4 devices, waist deep      -> severe, high confidence
      B: 1 report, knee deep                       -> restricted, low confidence
      C: 3 reports, one of them 8 hours old        -> confidence dragged down
      D: 5 reports from ONE device, waist deep     -> still ONE voice
    """
    now = now or int(time.time() * 1000)
    reports = []

    # A — a genuinely confirmed flooded street. Chained along 40 m gaps,
    # so single-link clustering should hold them together.
    for i in range(4):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 40, 0)
        reports.append(make_report(
            f"A{i}", lat, lon, device=f"dev-a{i}", water="waist",
            minutes_ago=10 + i * 5, rising=1, road="no", now=now))

    # B — one lonely report, 2 km east
    lat, lon = offset(BASE_LAT, BASE_LON, 0, 2000)
    reports.append(make_report("B0", lat, lon, device="dev-b",
                               water="knee", minutes_ago=20, now=now))

    # C — three reports 2 km north, but the newest is 4 hours old
    for i in range(3):
        lat, lon = offset(BASE_LAT, BASE_LON, 2000 + i * 50, 0)
        reports.append(make_report(
            f"C{i}", lat, lon, device=f"dev-c{i}", water="knee",
            minutes_ago=240 + i * 60, now=now))

    # D — one person filing five times from the same phone
    for i in range(5):
        lat, lon = offset(BASE_LAT, BASE_LON, 0, -2000 - i * 20)
        reports.append(make_report(
            f"D{i}", lat, lon, device="dev-d-single", water="waist",
            minutes_ago=15 + i, now=now))

    return {
        "reports": reports,
        "truth": {
            "expected_clusters": 4,
            "A": {"danger": "severe or red", "confidence": "high (>0.8)",
                  "why": "4 independent devices, all fresh"},
            "B": {"danger": "restricted", "confidence": "low (<0.55)",
                  "why": "a single report is a rumour"},
            "C": {"danger": "restricted", "confidence": "low",
                  "why": "all evidence is hours old, decay applies"},
            "D": {"danger": "severe", "confidence": "low (<0.55)",
                  "why": "five reports but ONE device is still one voice"},
        },
    }


def scene_contradiction(now=None):
    """
    Four people say a road is under water. A fifth says it is clear.

    The fifth must NOT erase the zone. It must be held for a human.
    This is the demo moment — get it right.
    """
    now = now or int(time.time() * 1000)
    reports = []
    for i in range(4):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 30, 0)
        reports.append(make_report(
            f"X{i}", lat, lon, device=f"dev-x{i}", water="waist",
            minutes_ago=30 + i * 10, road="no", now=now))

    lat, lon = offset(BASE_LAT, BASE_LON, 60, 20)
    reports.append(make_report(
        "LIAR", lat, lon, device="dev-liar", water=None,
        minutes_ago=5, road="yes", now=now))

    return {
        "reports": reports,
        "truth": {
            "expected_clusters": 1,
            "zone_danger": "severe or red",
            "held_report_ids": ["LIAR"],
            "why": "one report disagreeing with four confident ones is held, "
                   "not applied",
        },
    }


def scene_aerial(now=None):
    """
    Ground reports say knee deep. A fresh drone survey says waist.

    Direct observation should carry more weight than description.
    """
    now = now or int(time.time() * 1000)
    reports = []
    for i in range(2):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 50, 0)
        reports.append(make_report(
            f"G{i}", lat, lon, device=f"dev-g{i}", water="knee",
            minutes_ago=90 + i * 20, now=now))

    lat, lon = offset(BASE_LAT, BASE_LON, 25, 10)
    reports.append(make_report(
        "AER", lat, lon, device="drone-1", water="waist",
        minutes_ago=5, source="aerial", loc_conf=1.0, now=now))

    return {
        "reports": reports,
        "truth": {
            "expected_clusters": 1,
            "zone_danger": "severe",
            "why": "a fresh aerial survey outweighs older ground description",
        },
    }


def scene_load(n=200, now=None, seed=42):
    """A realistic district-scale pile, for timing and for seeding the demo."""
    random.seed(seed)
    now = now or int(time.time() * 1000)
    reports = []
    centres = [offset(BASE_LAT, BASE_LON,
                      random.uniform(-6000, 6000),
                      random.uniform(-6000, 6000)) for _ in range(12)]

    for i in range(n):
        clat, clon = random.choice(centres)
        lat, lon = offset(clat, clon, random.uniform(-120, 120),
                          random.uniform(-120, 120))
        reports.append(make_report(
            f"L{i}", lat, lon, device=f"dev-{random.randint(1, 45)}",
            water=random.choice(WATER_LEVELS),
            minutes_ago=random.randint(1, 400),
            rising=random.choice([0, 0, 1]),
            road=random.choice(["yes", "no", "unknown"]),
            loc_conf=random.choice([1.0, 1.0, 0.6]), now=now))

    return {"reports": reports, "truth": {"expected_clusters": "about 12"}}


if __name__ == "__main__":
    from .danger import build_danger_map
    scene = scene_basic()
    result = build_danger_map(scene["reports"])
    print("truth:", scene["truth"]["expected_clusters"], "clusters expected")
    print("got:  ", result["stats"])
    for z in result["zones"]:
        print(f"  {z['danger_name']:11} conf {z['confidence']:.2f}  "
              f"{z['routing']:10} {z['evidence']}")


# ============================================================ road scenes
# For routing. Same principle as the danger scenes: the right answer is
# written down before the algorithm runs.

def grid_town(rows=9, cols=9, spacing_m=200, base=(BASE_LAT, BASE_LON)):
    """
    A regular grid of streets. Node ids are "r,c".

    A grid is not what Assam looks like, but it is perfect for testing:
    every path length is predictable by hand, so when the router picks a
    route we can say whether it is right rather than whether it looks
    plausible.
    """
    from .routing import RoadGraph
    g = RoadGraph()
    blat, blon = base
    for r in range(rows):
        for c in range(cols):
            lat, lon = offset(blat, blon, r * spacing_m, c * spacing_m)
            g.add_node(f"{r},{c}", lat, lon)
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                g.add_edge(f"{r},{c}", f"{r},{c+1}", "residential")
            if r + 1 < rows:
                g.add_edge(f"{r},{c}", f"{r+1},{c}", "residential")
    return g


def scene_route_detour(now=None):
    """
    A fast road runs straight through the middle. The flood sits on it.

    An earlier version of this scene used a plain grid, and it was a bad
    test: on a grid every staircase path between two corners is the same
    length, so the naive router was not FORCED through the flooded block —
    it just happened to route around it, and the test passed for the wrong
    reason.

    Now the middle row is a fast road and everything else is residential.
    A router ignoring flooding will always take the fast road, because it
    genuinely is fastest. Ours has to give it up and pay for the detour.
    """
    now = now or int(time.time() * 1000)
    g = grid_town()

    # upgrade the middle row to a fast road
    for c in range(8):
        key = tuple(sorted((f"4,{c}", f"4,{c+1}")))
        g.edge_meta[key]["road_type"] = "highway"

    reports = []
    clat, clon = offset(BASE_LAT, BASE_LON, 4 * 200, 4 * 200)
    for i in range(4):
        lat, lon = offset(clat, clon, i * 25, 0)
        reports.append(make_report(f"R{i}", lat, lon, device=f"dev-r{i}",
                                   water="waist", minutes_ago=10 + i,
                                   road="no", now=now))
    return {
        "graph": g,
        "reports": reports,
        "start": "4,0",
        "goals": {"4,8"},
        "truth": {
            "naive_takes": "the fast middle road, straight through the water",
            "aware_must": "leave the fast road and detour on slower streets",
        },
    }


def scene_route_trapped(now=None):
    """
    A ring of confirmed flooding around the start. There is no way out.

    The right answer is "no route", clearly stated — NOT a route that
    quietly runs through water, and not a crash.
    """
    now = now or int(time.time() * 1000)
    g = grid_town(rows=7, cols=7)
    reports = []
    # confirmed zones on every edge leading out of the bottom-left corner
    ring = [(0, 2), (1, 2), (2, 2), (2, 1), (2, 0)]
    n = 0
    for (r, c) in ring:
        clat, clon = offset(BASE_LAT, BASE_LON, r * 200, c * 200)
        for i in range(4):
            lat, lon = offset(clat, clon, i * 20, 0)
            reports.append(make_report(f"T{n}", lat, lon, device=f"dev-t{n}",
                                       water="above", minutes_ago=5,
                                       road="no", now=now))
            n += 1
    return {
        "graph": g,
        "reports": reports,
        "start": "0,0",
        "goals": {"6,6"},
        "truth": {"expect_found": False,
                  "why": "the start is ringed by confirmed flooding"},
    }


def scene_route_last_resort(now=None):
    """
    The only way out crosses an UNCONFIRMED zone.

    We must still return a route, flagged as uncertain. Refusing to answer
    helps nobody, and a route with an honest label beats no route at all.
    """
    now = now or int(time.time() * 1000)
    g = grid_town(rows=7, cols=7)
    reports = []
    n = 0
    # confirmed on most of the ring
    for (r, c) in [(0, 2), (1, 2), (2, 2), (2, 1)]:
        clat, clon = offset(BASE_LAT, BASE_LON, r * 200, c * 200)
        for i in range(4):
            lat, lon = offset(clat, clon, i * 20, 0)
            reports.append(make_report(f"U{n}", lat, lon, device=f"dev-u{n}",
                                       water="above", minutes_ago=5,
                                       road="no", now=now))
            n += 1
    # ONE report on the last gap -> uncertain, not confirmed
    clat, clon = offset(BASE_LAT, BASE_LON, 2 * 200, 0)
    reports.append(make_report("SOLO", clat, clon, device="dev-solo",
                               water="knee", minutes_ago=8, now=now))
    return {
        "graph": g,
        "reports": reports,
        "start": "0,0",
        "goals": {"6,6"},
        "truth": {"expect_found": True, "expect_confidence": "uncertain",
                  "why": "one report is not enough to seal the last way out"},
    }
# ============================================================ road scenes
# For routing. Same principle as the danger scenes: the right answer is
# written down before the algorithm runs.
 
def grid_town(rows=9, cols=9, spacing_m=200, base=(BASE_LAT, BASE_LON)):
    """
    A regular grid of streets. Node ids are "r,c".
 
    A grid is not what Assam looks like, but it is perfect for testing:
    every path length is predictable by hand, so when the router picks a
    route we can say whether it is right rather than whether it looks
    plausible.
    """
    from .routing import RoadGraph
    g = RoadGraph()
    blat, blon = base
    for r in range(rows):
        for c in range(cols):
            lat, lon = offset(blat, blon, r * spacing_m, c * spacing_m)
            g.add_node(f"{r},{c}", lat, lon)
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                g.add_edge(f"{r},{c}", f"{r},{c+1}", "residential")
            if r + 1 < rows:
                g.add_edge(f"{r},{c}", f"{r+1},{c}", "residential")
    return g
 
 
def scene_route_detour(now=None):
    """
    A fast road runs straight through the middle. The flood sits on it.
 
    An earlier version of this scene used a plain grid, and it was a bad
    test: on a grid every staircase path between two corners is the same
    length, so the naive router was not FORCED through the flooded block —
    it just happened to route around it, and the test passed for the wrong
    reason.
 
    Now the middle row is a fast road and everything else is residential.
    A router ignoring flooding will always take the fast road, because it
    genuinely is fastest. Ours has to give it up and pay for the detour.
    """
    now = now or int(time.time() * 1000)
    g = grid_town()
 
    # upgrade the middle row to a fast road
    for c in range(8):
        key = tuple(sorted((f"4,{c}", f"4,{c+1}")))
        g.edge_meta[key]["road_type"] = "highway"
 
    reports = []
    clat, clon = offset(BASE_LAT, BASE_LON, 4 * 200, 4 * 200)
    for i in range(4):
        lat, lon = offset(clat, clon, i * 25, 0)
        reports.append(make_report(f"R{i}", lat, lon, device=f"dev-r{i}",
                                   water="waist", minutes_ago=10 + i,
                                   road="no", now=now))
    return {
        "graph": g,
        "reports": reports,
        "start": "4,0",
        "goals": {"4,8"},
        "truth": {
            "naive_takes": "the fast middle road, straight through the water",
            "aware_must": "leave the fast road and detour on slower streets",
        },
    }
 
 
def scene_route_trapped(now=None):
    """
    A ring of confirmed flooding around the start. There is no way out.
 
    The right answer is "no route", clearly stated — NOT a route that
    quietly runs through water, and not a crash.
    """
    now = now or int(time.time() * 1000)
    g = grid_town(rows=7, cols=7)
    reports = []
    # confirmed zones on every edge leading out of the bottom-left corner
    ring = [(0, 2), (1, 2), (2, 2), (2, 1), (2, 0)]
    n = 0
    for (r, c) in ring:
        clat, clon = offset(BASE_LAT, BASE_LON, r * 200, c * 200)
        for i in range(4):
            lat, lon = offset(clat, clon, i * 20, 0)
            reports.append(make_report(f"T{n}", lat, lon, device=f"dev-t{n}",
                                       water="above", minutes_ago=5,
                                       road="no", now=now))
            n += 1
    return {
        "graph": g,
        "reports": reports,
        "start": "0,0",
        "goals": {"6,6"},
        "truth": {"expect_found": False,
                  "why": "the start is ringed by confirmed flooding"},
    }
 
 
def scene_route_last_resort(now=None):
    """
    The only way out crosses an UNCONFIRMED zone.
 
    We must still return a route, flagged as uncertain. Refusing to answer
    helps nobody, and a route with an honest label beats no route at all.
    """
    now = now or int(time.time() * 1000)
    g = grid_town(rows=7, cols=7)
    reports = []
    n = 0
    # confirmed on most of the ring
    for (r, c) in [(0, 2), (1, 2), (2, 2), (2, 1)]:
        clat, clon = offset(BASE_LAT, BASE_LON, r * 200, c * 200)
        for i in range(4):
            lat, lon = offset(clat, clon, i * 20, 0)
            reports.append(make_report(f"U{n}", lat, lon, device=f"dev-u{n}",
                                       water="above", minutes_ago=5,
                                       road="no", now=now))
            n += 1
    # ONE report on the last gap -> uncertain, not confirmed
    clat, clon = offset(BASE_LAT, BASE_LON, 2 * 200, 0)
    reports.append(make_report("SOLO", clat, clon, device="dev-solo",
                               water="knee", minutes_ago=8, now=now))
    return {
        "graph": g,
        "reports": reports,
        "start": "0,0",
        "goals": {"6,6"},
        "truth": {"expect_found": True, "expect_confidence": "uncertain",
                  "why": "one report is not enough to seal the last way out"},
    }