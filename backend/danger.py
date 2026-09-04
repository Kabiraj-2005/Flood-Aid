"""
Turning a pile of reports into a danger map.

Three separate ideas live here, and keeping them separate is the whole
point:

  1. CLUSTERING   which reports are about the same place
  2. DANGER       how bad it is            (from what reports SAY)
  3. CONFIDENCE   how sure we are          (from how many agree, and how old)

Danger does not rise with time. A zone that goes quiet does not become
more dangerous — it becomes less certain, and the map says so.

An area with no reports is neither safe nor dangerous. It is UNKNOWN, and
we show it as unknown. We do not claim to know what nobody has told us.
"""

import math
import time
from collections import defaultdict

# ---------------------------------------------------------------- tuning
# These are judgement calls about floods, not about code. Change them here
# and nowhere else.

CLUSTER_RADIUS_M = 150.0      # two reports closer than this are the same place
CONFIDENCE_HALF_LIFE_H = 3.0  # a report is worth half as much after 3 hours
CONFIRM_THRESHOLD = 0.55      # at or above this, a zone is acted on

# How high confidence can go given N independent devices. This is the rule
# "one report is a rumour, three agreeing is a fact", written down. Without
# it a single fresh report reaches 0.66 and blocks roads on its own.
CORROBORATION_CAP = {1: 0.45, 2: 0.75}   # 3+ devices: no cap
HOLD_THRESHOLD = 0.25         # below this, we do not draw it at all
STALE_HOURS = 6.0             # older than this and even a confirmed zone
                              # drops to "uncertain" for routing

# ------------------------------------------------------- danger levels

SAFE, CAUTION, RESTRICTED, SEVERE, RED = 0, 1, 2, 3, 4

DANGER_NAMES = {
    SAFE: "safe",
    CAUTION: "caution",
    RESTRICTED: "restricted",
    SEVERE: "severe",
    RED: "red",
}

DANGER_MEANING = {
    SAFE: "passable on foot and by vehicle",
    CAUTION: "ankle deep, slow going",
    RESTRICTED: "knee deep, no vehicles",
    SEVERE: "waist deep, boat only",
    RED: "above waist or rising fast, rescue territory",
}

# what a report's water_level implies on its own
DEPTH_TO_DANGER = {
    None: SAFE,
    "": SAFE,
    "ankle": CAUTION,
    "knee": RESTRICTED,
    "waist": SEVERE,
    "above": RED,
}


# ------------------------------------------------------------- geometry

def haversine_m(lat1, lon1, lat2, lon2):
    """Distance between two points on the earth, in metres."""
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ------------------------------------------------------------ clustering

def cluster_reports(reports, radius_m=CLUSTER_RADIUS_M):
    """
    Group reports that are about the same place.

    Single-link: if A is within radius of B, they are the same incident,
    even if A and C are further apart than the radius. A flooded street is
    long and thin — chaining along it is correct behaviour, not a bug.

    Reports with no location cannot be clustered. They go into their own
    single-report group and end up in the review queue, because we cannot
    put them on a map.

    Returns a list of lists.
    """
    located = [r for r in reports if r.get("lat") is not None
                                  and r.get("lon") is not None]
    unlocated = [r for r in reports if r.get("lat") is None
                                    or r.get("lon") is None]

    parent = {r["id"]: r["id"] for r in located}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]     # path compression
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # O(n^2). Fine for hundreds of reports. If we ever have tens of
    # thousands, bucket by geohash first — do NOT optimise before then.
    for i, a in enumerate(located):
        for b in located[i + 1:]:
            if haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) <= radius_m:
                union(a["id"], b["id"])

    groups = defaultdict(list)
    for r in located:
        groups[find(r["id"])].append(r)

    out = list(groups.values())
    out.extend([[r] for r in unlocated])
    return out


# ------------------------------------------------------------ confidence

def report_weight(report, now_ms):
    """
    How much this single report is worth right now.

    Three things reduce it:
      - age, on a half-life curve. Water moves.
      - how sure we were of its location
      - how sure the extraction was

    A drone survey starts higher than a text report, because it is direct
    observation rather than somebody's description.
    """
    seen = report.get("synced_at") or report.get("reported_at") or now_ms
    hours = max(0.0, (now_ms - seen) / 3_600_000)
    freshness = 0.5 ** (hours / CONFIDENCE_HALF_LIFE_H)

    base = 1.0 if report.get("source") == "aerial" else 0.7

    loc = report.get("location_confidence")
    loc = 1.0 if loc is None else max(0.2, min(1.0, loc))

    ext = report.get("extraction_confidence") or 0.0
    ext = 1.0 if ext == 0.0 else max(0.3, min(1.0, ext))   # 0 means "not run yet"

    return base * freshness * loc * ext


def cluster_confidence(group, now_ms):
    """
    How sure we are about this place, 0 to 1.

    Independent reports agreeing push it up, with diminishing returns — the
    fourth report adds less than the second. Reports from the SAME device
    do not count as independent agreement; one person filing five times is
    still one person.
    """
    by_device = defaultdict(list)
    for r in group:
        by_device[r.get("device_id") or r["id"]].append(r)

    # one vote per device: its strongest report
    votes = [max(report_weight(r, now_ms) for r in reports)
             for reports in by_device.values()]

    if not votes:
        return 0.0

    # 1 - product(1 - w) : classic "at least one of these is right"
    disagree = 1.0
    for w in votes:
        disagree *= (1.0 - min(w, 0.95))
    conf = 1.0 - disagree

    # Corroboration cap. One person filing five times is still one person,
    # and must not be able to close a road by themselves.
    #
    # Exception: a drone survey is direct observation, not a description,
    # so it can confirm on its own.
    has_aerial = any(r.get("source") == "aerial" for r in group)
    if not has_aerial:
        cap = CORROBORATION_CAP.get(len(votes))
        if cap is not None:
            conf = min(conf, cap)

    return round(conf, 3)


# ---------------------------------------------------------- danger level

def cluster_danger(group, now_ms, exclude=None):
    """
    How bad this place is, on the 5-level scale.

    `exclude` is the set of report ids that have been held as contradicting
    the group. They must not influence the level — see the two-pass note in
    build_danger_map.

    Weighted by how much each report is worth, so a fresh report counts
    more than a stale one. We lean towards the worse reading when reports
    disagree — under-calling a flood is more dangerous than over-calling it.
    """
    exclude = exclude or set()
    scored = [(DEPTH_TO_DANGER.get(r.get("water_level"), SAFE),
               report_weight(r, now_ms), r)
              for r in group if r["id"] not in exclude]
    scored = [(d, w, r) for d, w, r in scored if w > 0.01]
    if not scored:
        return SAFE

    # Support for each level, counted PER DEVICE.
    #
    # A plain weighted average is the obvious approach and it is wrong: one
    # very fresh outlier saying "all clear" drags the mean down and demotes
    # a zone four people confirmed. Counting per level, per device, means a
    # lone voice cannot outweigh a group however recent it is.
    support = defaultdict(float)
    devices = defaultdict(set)
    for d, w, r in scored:
        dev = r.get("device_id") or r["id"]
        if w > support[(d, dev)]:
            support[(d, dev)] = w
        devices[d].add(dev)

    level_weight = defaultdict(float)
    for (d, _dev), w in support.items():
        level_weight[d] += w

    level = max(level_weight, key=lambda d: (level_weight[d], d))

    # Lean towards the worse reading when two levels are close. Under-calling
    # a flood is more dangerous than over-calling it.
    for d in sorted(level_weight, reverse=True):
        if d > level and level_weight[d] >= 0.8 * level_weight[level]:
            level = d
            break

    # rising water or a cut-off road pushes it up a step
    if any(r.get("rising") for _, _, r in scored) and level < RED:
        level += 1
    if any(r.get("road_passable") == "no" for _, _, r in scored):
        level = max(level, RESTRICTED)

    return max(SAFE, min(RED, level))


def _devices_claiming(group, level, now_ms):
    """How many distinct devices report this danger level."""
    return len({
        r.get("device_id") or r["id"] for r in group
        if DEPTH_TO_DANGER.get(r.get("water_level"), SAFE) == level
        and report_weight(r, now_ms) > 0.01
    })


# ------------------------------------------------------ contradictions

def find_contradictions(group, now_ms, majority=None):
    """
    Reports that disagree with the confident majority of their group.

    A single report saying "the road is clear" must NOT erase a zone that
    four other people confirmed. It is held for a human instead.

    Returns the reports to hold, with a reason.
    """
    if len(group) < 2:
        return []

    majority = cluster_danger(group, now_ms) if majority is None else majority
    conf = cluster_confidence(group, now_ms)

    # nothing is confident enough here to contradict
    if conf < CONFIRM_THRESHOLD:
        return []

    majority_devices = _devices_claiming(group, majority, now_ms)

    held = []
    for r in group:
        claim = DEPTH_TO_DANGER.get(r.get("water_level"), SAFE)
        if claim == majority:
            continue

        # How many OTHER devices back this report's claim?
        backing = _devices_claiming(group, claim, now_ms)

        # A drone survey is direct observation. It is allowed to disagree.
        if r.get("source") == "aerial":
            continue

        # Hold when a report disagrees by two or more levels and is
        # essentially alone against a corroborated group.
        #
        # The test is CORROBORATION, not freshness. An earlier version held
        # a report only if its weight was low, which meant a very recent
        # "all clear" sailed through and demoted the zone. Being recent is
        # not the same as being right.
        if abs(claim - majority) >= 2 and backing < majority_devices:
            held.append({
                "report_id": r["id"],
                "claims": DANGER_NAMES[claim],
                "group_says": DANGER_NAMES[majority],
                "group_confidence": conf,
                # This line is read by a human officer deciding what to do,
                # so it must be exactly true. len(group) would include the
                # contradicting report itself in "how many agree".
                "reason": (
                    f"reports {DANGER_NAMES[claim]}, but {majority_devices} "
                    f"other devices here agree on {DANGER_NAMES[majority]}"
                ),
            })
    return held


# ---------------------------------------------------------- the map call

def build_danger_map(reports, now_ms=None, radius_m=None):
    """
    The whole pipeline. Reports in, zones out.

    Returns:
      zones  — what we draw and route around
      held   — reports waiting for a human
      stats  — for the control room footer

    A zone with confidence below HOLD_THRESHOLD is not drawn at all. We do
    not put a rumour on a map.

    ``radius_m`` overrides CLUSTER_RADIUS_M for this call only — the actual
    tuning constant still lives at the top of this file; this is for
    sensitivity analysis (see benchmark_realistic.py), not retuning.
    """
    now_ms = now_ms or int(time.time() * 1000)
    radius_m = CLUSTER_RADIUS_M if radius_m is None else radius_m
    groups = cluster_reports(reports, radius_m=radius_m)

    zones, held = [], []

    for i, group in enumerate(groups):
        located = [r for r in group if r.get("lat") is not None]
        if not located:
            # no location: cannot map it, send it for review
            for r in group:
                held.append({
                    "report_id": r["id"],
                    "reason": "no usable location",
                    "claims": None, "group_says": None, "group_confidence": 0.0,
                })
            continue

        # TWO PASSES, and the order matters.
        #
        # Pass 1 gives a provisional level from every report in the group.
        # Pass 2 finds the reports that contradict it, then recomputes the
        # level with those excluded.
        #
        # Without the second pass a single fresh "all clear" drags the
        # weighted average down and quietly demotes a zone that four people
        # confirmed — which is the exact failure this feature exists to
        # prevent. Holding a report for review is pointless if it has
        # already changed the map on its way to the queue.
        provisional = cluster_danger(group, now_ms)
        contradictions = find_contradictions(group, now_ms, provisional)
        held.extend(contradictions)

        excluded = {h["report_id"] for h in contradictions}
        danger = cluster_danger(group, now_ms, exclude=excluded)
        conf = cluster_confidence(
            [r for r in group if r["id"] not in excluded], now_ms)

        supporting = [r for r in group if r["id"] not in excluded] or group
        newest = max(r.get("synced_at") or r.get("reported_at") or 0
                     for r in supporting)
        age_h = max(0.0, (now_ms - newest) / 3_600_000)

        # what routing should do with this zone
        if conf < HOLD_THRESHOLD or danger == SAFE:
            routing = "ignore"
        elif conf >= CONFIRM_THRESHOLD and age_h <= STALE_HOURS:
            routing = "block"          # delete these roads
        else:
            routing = "expensive"      # 5x cost, used only if nothing else

        zone = {
            "cluster_id": f"z-{i}",
            "lat": sum(r["lat"] for r in located) / len(located),
            "lon": sum(r["lon"] for r in located) / len(located),
            "radius_m": _zone_radius(located, radius_m),
            "danger": danger,
            "danger_name": DANGER_NAMES[danger],
            "meaning": DANGER_MEANING[danger],
            "confidence": conf,
            "report_count": len(supporting),
            "device_count": len({r.get("device_id") for r in supporting}),
            "held_count": len(excluded),
            "has_aerial": any(r.get("source") == "aerial" for r in supporting),
            "newest_age_hours": round(age_h, 2),
            "routing": routing,
            "report_ids": [r["id"] for r in supporting],
            # everything the UI needs to say WHY, in one line
            "evidence": (
                f"{len(supporting)} reports from "
                f"{len({r.get('device_id') for r in supporting})} devices, "
                f"newest {round(age_h, 1)} h ago"
                + (f", {len(excluded)} held" if excluded else "")
            ),
        }

        if conf >= HOLD_THRESHOLD and danger > SAFE:
            zones.append(zone)

    zones.sort(key=lambda z: (-z["danger"], -z["confidence"]))

    return {
        "zones": zones,
        "held": held,
        "stats": {
            "reports": len(reports),
            "clusters": len(groups),
            "zones_drawn": len(zones),
            "blocked": sum(1 for z in zones if z["routing"] == "block"),
            "expensive": sum(1 for z in zones if z["routing"] == "expensive"),
            "held_for_review": len(held),
            "unknown_area": "not claimed — no reports, no colour",
        },
    }


def _zone_radius(located, radius_m=CLUSTER_RADIUS_M):
    """How far the reports in this zone spread, plus the cluster radius."""
    if len(located) == 1:
        return radius_m
    clat = sum(r["lat"] for r in located) / len(located)
    clon = sum(r["lon"] for r in located) / len(located)
    furthest = max(haversine_m(clat, clon, r["lat"], r["lon"]) for r in located)
    return round(furthest + radius_m, 1)
