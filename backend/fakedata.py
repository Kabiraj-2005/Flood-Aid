"""
Fake data with known answers hidden inside.

This is C's first job and it must exist BEFORE the thing it measures.
Without it we cannot tell whether the clustering works or merely looks
plausible on a screen.

Every generated scene carries a `truth` block saying what the right answer
is. Then we score ourselves honestly instead of guessing.

    python3 -m backend.fakedata          # print a scene
"""

import math
import random
import time

from .danger import DANGER_NAMES, DEPTH_TO_DANGER, haversine_m

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
                road="unknown", loc_conf=1.0, now=None, rng=None):
    """``rng`` must be an explicitly seeded random.Random. Falling back to
    the bare `random` module means "whatever state the global RNG happens
    to be in" — not reproducible from a seed. Every caller in this file
    passes its own seeded instance; do not add a call site that doesn't.
    """
    rng = rng or random
    now = now or int(time.time() * 1000)
    t = now - minutes_ago * 60_000
    return {
        "id": rid,
        "device_id": device,
        "counter": 1,
        "phone_time": t,
        "source": source,
        "text": rng.choice(ASSAMESE_SNIPPETS + MIXED_SNIPPETS),
        "photo_ids": [],
        "lat": lat, "lon": lon, "polygon": None,
        "location_confidence": loc_conf,
        "people_count": people if people is not None else rng.randint(2, 20),
        "injured": injured,
        "children_elderly": rng.choice([0, 0, 1]),
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


def scene_basic(now=None, seed=1001):
    """
    Four separate places, known in advance.

      A: 4 reports from 4 devices, waist deep      -> severe, high confidence
      B: 1 report, knee deep                       -> restricted, low confidence
      C: 3 reports, one of them 8 hours old        -> confidence dragged down
      D: 5 reports from ONE device, waist deep     -> still ONE voice
    """
    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    reports = []

    # A — a genuinely confirmed flooded street. Chained along 40 m gaps,
    # so single-link clustering should hold them together.
    for i in range(4):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 40, 0)
        reports.append(make_report(
            f"A{i}", lat, lon, device=f"dev-a{i}", water="waist",
            minutes_ago=10 + i * 5, rising=1, road="no", now=now, rng=rng))

    # B — one lonely report, 2 km east
    lat, lon = offset(BASE_LAT, BASE_LON, 0, 2000)
    reports.append(make_report("B0", lat, lon, device="dev-b",
                               water="knee", minutes_ago=20, now=now, rng=rng))

    # C — three reports 2 km north, but the newest is 4 hours old
    for i in range(3):
        lat, lon = offset(BASE_LAT, BASE_LON, 2000 + i * 50, 0)
        reports.append(make_report(
            f"C{i}", lat, lon, device=f"dev-c{i}", water="knee",
            minutes_ago=240 + i * 60, now=now, rng=rng))

    # D — one person filing five times from the same phone
    for i in range(5):
        lat, lon = offset(BASE_LAT, BASE_LON, 0, -2000 - i * 20)
        reports.append(make_report(
            f"D{i}", lat, lon, device="dev-d-single", water="waist",
            minutes_ago=15 + i, now=now, rng=rng))

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


def scene_contradiction(now=None, seed=1002):
    """
    Four people say a road is under water. A fifth says it is clear.

    The fifth must NOT erase the zone. It must be held for a human.
    This is the demo moment — get it right.
    """
    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    reports = []
    for i in range(4):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 30, 0)
        reports.append(make_report(
            f"X{i}", lat, lon, device=f"dev-x{i}", water="waist",
            minutes_ago=30 + i * 10, road="no", now=now, rng=rng))

    lat, lon = offset(BASE_LAT, BASE_LON, 60, 20)
    reports.append(make_report(
        "LIAR", lat, lon, device="dev-liar", water=None,
        minutes_ago=5, road="yes", now=now, rng=rng))

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


def scene_aerial(now=None, seed=1003):
    """
    Ground reports say knee deep. A fresh drone survey says waist.

    Direct observation should carry more weight than description.
    """
    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    reports = []
    for i in range(2):
        lat, lon = offset(BASE_LAT, BASE_LON, i * 50, 0)
        reports.append(make_report(
            f"G{i}", lat, lon, device=f"dev-g{i}", water="knee",
            minutes_ago=90 + i * 20, now=now, rng=rng))

    lat, lon = offset(BASE_LAT, BASE_LON, 25, 10)
    reports.append(make_report(
        "AER", lat, lon, device="drone-1", water="waist",
        minutes_ago=5, source="aerial", loc_conf=1.0, now=now, rng=rng))

    return {
        "reports": reports,
        "truth": {
            "expected_clusters": 1,
            "zone_danger": "severe",
            "why": "a fresh aerial survey outweighs older ground description",
        },
    }


def scene_hard_clustering(now=None, seed=3001):
    """
    Purpose-built to stress single-link clustering's two opposite failure
    modes at once, so a chosen CLUSTER_RADIUS_M can't dodge one by tripping
    the other:

      - I0 / I1: two genuine, separate incidents whose centres are 200 m
        apart — just outside the default 150 m CLUSTER_RADIUS_M. At the
        default radius they must stay two zones. If they merge, the radius
        is too generous.
      - STREET: one real incident, a flooded street 400 m long, reported
        roughly every 60 m along its length. Single-link chaining must hold
        it together as ONE zone even though its own span is far bigger than
        CLUSTER_RADIUS_M. If it splits, the radius is too tight.

    Report ids encode nothing about incident identity beyond a bare index —
    the truth block, not the payload, is what scoring reads.
    """
    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    reports = []
    truth_incidents = []

    def add_point_incident(incident_id, centre, n_reports, n_devices, tag):
        clat, clon = centre
        devices = [f"dev-{tag}-{i}" for i in range(n_devices)]
        ids = []
        for i in range(n_reports):
            # A tight few-metre footprint: this is one place, not a spread.
            radius = 15.0 * math.sqrt(rng.random())
            angle = rng.uniform(0, 2 * math.pi)
            lat, lon = offset(clat, clon,
                               radius * math.cos(angle), radius * math.sin(angle))
            rid = f"{tag}-{i}"
            ids.append(rid)
            reports.append(make_report(
                rid, lat, lon, device=rng.choice(devices), water="waist",
                minutes_ago=rng.randint(5, 25), rising=1, road="no",
                now=now, rng=rng))
        truth_incidents.append({
            "incident_id": incident_id, "kind": "point",
            "center": {"lat": clat, "lon": clon}, "report_ids": ids,
        })

    gap_m = 200.0  # centre-to-centre distance between I0 and I1
    c0 = (BASE_LAT, BASE_LON)
    c1 = offset(BASE_LAT, BASE_LON, 0, gap_m)
    add_point_incident("I0", c0, 4, 3, "P0")
    add_point_incident("I1", c1, 4, 3, "P1")

    # STREET: far from I0/I1 so the radius sweep can't accidentally connect
    # them — this incident is testing splitting, not merging.
    street_start = offset(BASE_LAT, BASE_LON, 3000, 0)
    span_m = 400.0
    n_gaps = 7  # 8 points, ~57 m apart on average -> "roughly every 60 m"
    ids = []
    travelled = 0.0
    prev = street_start
    max_gap_m = 0.0
    for i in range(n_gaps + 1):
        if i:
            gap = (span_m / n_gaps) * rng.uniform(0.9, 1.1)
            travelled += gap
        # a couple of metres of cross-street GPS wobble
        lat, lon = offset(street_start[0], street_start[1],
                           travelled, rng.uniform(-3, 3))
        if i:
            max_gap_m = max(max_gap_m, haversine_m(prev[0], prev[1], lat, lon))
        prev = (lat, lon)
        rid = f"ST-{i}"
        ids.append(rid)
        reports.append(make_report(
            rid, lat, lon, device=f"dev-street-{i}", water="waist",
            minutes_ago=rng.randint(5, 25), rising=1, road="no",
            now=now, rng=rng))
    truth_incidents.append({
        "incident_id": "STREET", "kind": "line", "report_ids": ids,
        "span_m": span_m, "max_consecutive_gap_m": round(max_gap_m, 1),
    })

    rng.shuffle(reports)

    return {
        "reports": reports,
        "truth": {
            "incidents": truth_incidents,
            "point_gap_m": gap_m,
            "street_span_m": span_m,
        },
    }


def score_hard_clustering(scene, result):
    """Score a build_danger_map result against a scene_hard_clustering truth.

    Unlike score_realistic, this reads which produced zone each known report
    id landed in directly — exact, since every report's true incident is
    known by construction rather than approximated from a circular footprint,
    which would misjudge the elongated STREET incident. Reports left out of
    every zone (held, or in a zone whose confidence never cleared the
    drawing threshold) count as neither merged nor split; they're reported
    separately as `unresolved`.
    """
    truth_incidents = scene["truth"]["incidents"]
    id_to_incident = {rid: inc["incident_id"]
                       for inc in truth_incidents for rid in inc["report_ids"]}

    zone_truth_ids = []          # per zone: set of truth incident ids touched
    incident_zone_indices = {}   # truth incident id -> set of zone indices it appears in
    for zi, zone in enumerate(result["zones"]):
        touched = set()
        for rid in zone["report_ids"]:
            tid = id_to_incident.get(rid)
            if tid is not None:
                touched.add(tid)
                incident_zone_indices.setdefault(tid, set()).add(zi)
        zone_truth_ids.append(touched)

    merges = [sorted(ids) for ids in zone_truth_ids if len(ids) > 1]
    splits = [tid for tid, zones_seen in incident_zone_indices.items()
              if len(zones_seen) > 1]

    mapped_ids = {rid for zone in result["zones"] for rid in zone["report_ids"]}
    unresolved = [rid for rid in id_to_incident if rid not in mapped_ids]

    return {
        "merges": len(merges),
        "merged_incident_pairs": merges,
        "splits": len(splits),
        "split_incidents": splits,
        "unresolved": len(unresolved),
    }


def _level_step(level, delta):
    """Move a water level up/down while staying inside the four observed levels."""
    i = WATER_LEVELS.index(level)
    return WATER_LEVELS[max(0, min(len(WATER_LEVELS) - 1, i + delta))]


def _pick_separated_centres(count, seed):
    """Make incident centres far enough apart that geography, not luck, drives clustering."""
    rng = random.Random(seed)
    centres = []
    attempts = 0
    while len(centres) < count and attempts < count * 1000:
        attempts += 1
        candidate = offset(
            BASE_LAT, BASE_LON,
            rng.uniform(-5500, 5500),
            rng.uniform(-5500, 5500),
        )
        if all(haversine_m(candidate[0], candidate[1], c[0], c[1]) >= 500
               for c in centres):
            centres.append(candidate)
    if len(centres) != count:
        raise RuntimeError("could not place separated synthetic incidents")
    return centres


def scene_realistic(n=240, incidents=12, now=None, seed=2026, accuracy=0.82,
                     centres=None):
    """Generate a district where each incident has a hidden physical truth.

    The important difference from ``scene_load`` is that reports are *observations*
    of a shared underlying incident, not independent random water levels.

    Each incident gets:
      - a hidden true water level;
      - a geographic centre and a compact footprint;
      - several devices, with some devices filing more than once;
      - mostly correct reports plus a small amount of adjacent-level noise;
      - realistic report ages and location uncertainty.

    ``accuracy`` is the probability a single observation matches the hidden
    true water level (default 0.82, matching the original fixed noise model).
    The remaining probability mass is split between adjacent-level noise and
    arbitrary outliers in the same 14:4 ratio the original model used, so
    lowering accuracy makes observations noisier without changing the *kind*
    of noise.

    ``centres`` overrides where incidents are placed — exactly ``incidents``
    (lat, lon) pairs. Default is scattered, mutually separated points picked
    at random (fine for benchmarking clustering in isolation). A caller that
    needs incidents to land somewhere specific, such as on top of a road
    network for a routing demo, supplies its own centres instead.

    ``truth`` is deliberately separate from the report payload. The clustering and
    danger code never sees it; the test suite uses it afterwards to measure error.
    """
    if n < incidents:
        raise ValueError("n must be at least the number of incidents")
    if incidents < 1:
        raise ValueError("incidents must be positive")
    if not 0.0 < accuracy <= 1.0:
        raise ValueError("accuracy must be in (0, 1]")

    remainder = 1.0 - accuracy
    adjacent_p = remainder * (14 / 18)
    outlier_p = remainder - adjacent_p
    adjacent_threshold = accuracy + adjacent_p

    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    if centres is None:
        centres = _pick_separated_centres(incidents, seed + 1)
    elif len(centres) != incidents:
        raise ValueError("centres must have exactly `incidents` entries")

    # More severe incidents are somewhat less common, but all four states occur.
    truth_levels = rng.choices(
        WATER_LEVELS,
        weights=[3, 4, 3, 2],
        k=incidents,
    )

    # Ensure the benchmark exercises the full scale when the scene is large enough.
    for i, level in enumerate(WATER_LEVELS):
        if i < incidents:
            truth_levels[i] = level

    counts = [n // incidents] * incidents
    for i in range(n % incidents):
        counts[i] += 1

    reports = []
    truth_incidents = []
    report_no = 0

    for incident_idx, ((clat, clon), true_level, count) in enumerate(
            zip(centres, truth_levels, counts)):
        # 3–7 devices means corroboration is real, while repeated observations
        # from one device remain possible.
        device_count = min(count, rng.randint(3, 7))
        # Opaque device identifiers: they must not encode the hidden incident.
        # The benchmark truth is the only place where incident membership exists.
        devices = [f"dev-{rng.getrandbits(64):016x}" for _ in range(device_count)]

        incident_report_ids = []
        for j in range(count):
            # Uniform disk sampling: reports cluster around a real place instead
            # of forming an artificial square.
            radius = 75.0 * math.sqrt(rng.random())
            angle = rng.uniform(0, 2 * math.pi)
            north = radius * math.cos(angle)
            east = radius * math.sin(angle)
            lat, lon = offset(clat, clon, north, east)

            device = rng.choice(devices)

            # Most observations match reality. A smaller fraction is one level
            # away; a few are deliberately bad observations.
            roll = rng.random()
            if roll < accuracy:
                observed = true_level
            elif roll < adjacent_threshold:
                observed = _level_step(true_level, rng.choice([-1, 1]))
            else:
                observed = rng.choice(WATER_LEVELS)

            # Some reports are deliberately stale so freshness can be measured,
            # but the majority describe the current situation.
            age_minutes = int(max(2, rng.triangular(5, 360, 35)))
            loc_conf = rng.choice([1.0, 1.0, 0.9, 0.7])
            rising = int(
                (true_level in ("waist", "above") and rng.random() < 0.35)
                or rng.random() < 0.04
            )
            road = "no" if true_level in ("waist", "above") and rng.random() < 0.75 else (
                "yes" if true_level == "ankle" and rng.random() < 0.8 else "unknown"
            )

            # Opaque report ID: no incident index, sequence, or other ground-truth
            # information is encoded in the report payload.
            rid = f"r-{rng.getrandbits(96):024x}"
            report_no += 1
            incident_report_ids.append(rid)
            reports.append(make_report(
                rid, lat, lon,
                device=device,
                water=observed,
                minutes_ago=age_minutes,
                people=rng.randint(2, 18),
                injured=1 if rng.random() < 0.05 else 0,
                rising=rising,
                road=road,
                loc_conf=loc_conf,
                now=now,
                rng=rng,
            ))

        truth_incidents.append({
            "incident_id": f"I{incident_idx:02d}",
            "center": {"lat": clat, "lon": clon},
            "true_water_level": true_level,
            "true_danger": DANGER_NAMES[DEPTH_TO_DANGER[true_level]],
            "report_ids": incident_report_ids,
            "report_count": count,
            "device_count": device_count,
        })

    # Shuffle arrival order: the algorithm must not get an easy incident-by-incident
    # ordering from the generator.
    rng.shuffle(reports)

    return {
        "reports": reports,
        "truth": {
            "expected_clusters": incidents,
            "incidents": truth_incidents,
            "noise_model": {
                "correct_observation_probability": accuracy,
                "adjacent_level_probability": adjacent_p,
                "arbitrary_outlier_probability": outlier_p,
                "max_report_radius_m": 75,
                "min_centre_separation_m": 500,
            },
        },
    }


def score_realistic(scene, result, slack_m=50.0):
    """Score a build_danger_map result against a scene_realistic truth block.

    Scores by geometry only: a produced zone (its centroid and radius, taken
    straight from ``result["zones"]``) either contains a hidden incident's
    true center or it doesn't — exactly like a human checking the map would.
    Never looks at report ids or the truth's report_ids lists.
    """
    truth_incidents = scene["truth"]["incidents"]

    def incidents_within(zone):
        return [
            inc["incident_id"] for inc in truth_incidents
            if haversine_m(zone["lat"], zone["lon"],
                            inc["center"]["lat"], inc["center"]["lon"])
               <= zone["radius_m"] + slack_m
        ]

    zone_incidents = [incidents_within(z) for z in result["zones"]]

    # A merge is a produced zone whose footprint contains more than one
    # hidden incident's true center.
    merges = [ids for ids in zone_incidents if len(ids) > 1]

    # A split is a hidden incident whose true center falls inside more than
    # one produced zone's footprint.
    incident_zone_counts = {i["incident_id"]: 0 for i in truth_incidents}
    for ids in zone_incidents:
        for incident_id in ids:
            incident_zone_counts[incident_id] += 1
    splits = [incident_id for incident_id, count in incident_zone_counts.items()
              if count > 1]

    # A hidden incident is recovered when exactly one produced zone's
    # footprint contains its true center.
    recovered = sum(1 for count in incident_zone_counts.values() if count == 1)

    return {
        "recovered": recovered,
        "total": len(truth_incidents),
        "merges": len(merges),
        "splits": len(splits),
        "held": len(result["held"]),
    }


def scene_load(n=200, now=None, seed=42):
    """A realistic district-scale pile, for timing and for seeding the demo."""
    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    reports = []
    centres = [offset(BASE_LAT, BASE_LON,
                      rng.uniform(-6000, 6000),
                      rng.uniform(-6000, 6000)) for _ in range(12)]

    for i in range(n):
        clat, clon = rng.choice(centres)
        lat, lon = offset(clat, clon, rng.uniform(-120, 120),
                          rng.uniform(-120, 120))
        reports.append(make_report(
            f"L{i}", lat, lon, device=f"dev-{rng.randint(1, 45)}",
            water=rng.choice(WATER_LEVELS),
            minutes_ago=rng.randint(1, 400),
            rising=rng.choice([0, 0, 1]),
            road=rng.choice(["yes", "no", "unknown"]),
            loc_conf=rng.choice([1.0, 1.0, 0.6]), now=now, rng=rng))

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
