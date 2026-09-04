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


def scene_realistic(n=240, incidents=12, now=None, seed=2026):
    """Generate a district where each incident has a hidden physical truth.

    The important difference from ``scene_load`` is that reports are *observations*
    of a shared underlying incident, not independent random water levels.

    Each incident gets:
      - a hidden true water level;
      - a geographic centre and a compact footprint;
      - several devices, with some devices filing more than once;
      - mostly correct reports plus a small amount of adjacent-level noise;
      - realistic report ages and location uncertainty.

    ``truth`` is deliberately separate from the report payload. The clustering and
    danger code never sees it; the test suite uses it afterwards to measure error.
    """
    if n < incidents:
        raise ValueError("n must be at least the number of incidents")
    if incidents < 1:
        raise ValueError("incidents must be positive")

    rng = random.Random(seed)
    now = now or int(time.time() * 1000)
    centres = _pick_separated_centres(incidents, seed + 1)

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
            if roll < 0.82:
                observed = true_level
            elif roll < 0.96:
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
                "correct_observation_probability": 0.82,
                "adjacent_level_probability": 0.14,
                "arbitrary_outlier_probability": 0.04,
                "max_report_radius_m": 75,
                "min_centre_separation_m": 500,
            },
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
