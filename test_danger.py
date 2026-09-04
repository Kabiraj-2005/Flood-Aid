"""
Score the danger map against known answers.

Every scene in fakedata.py carries a `truth` block. This file checks we
actually match it, rather than merely producing something plausible.

    python3 test_danger.py
"""

import time
from backend.danger import (
    build_danger_map, cluster_reports, haversine_m,
    DANGER_NAMES, CONFIRM_THRESHOLD, SEVERE, RED, RESTRICTED,
)
from backend import fakedata

NOW = int(time.time() * 1000)
ok = lambda msg: print("  pass  " + msg)


def show(result):
    for z in result["zones"]:
        print(f"        {z['danger_name']:11} conf {z['confidence']:.2f}  "
              f"{z['routing']:10} {z['evidence']}")


# ---------------------------------------------------------------- geometry
print("\ngeometry")
d = haversine_m(26.25, 92.34, 26.25 + 150 / 111320, 92.34)
assert 145 < d < 155, d
ok(f"150 m offset measures {d:.1f} m")


# ------------------------------------------------------------ scene basic
print("\nscene: four known places")
scene = fakedata.scene_basic(NOW)
res = build_danger_map(scene["reports"], NOW)
show(res)

assert res["stats"]["clusters"] == 4, res["stats"]
ok("found 4 clusters, as expected")

zones = {z["report_ids"][0][0]: z for z in res["zones"]}   # keyed by A/B/C/D

# A: four independent fresh devices -> confident, blocking
a = zones["A"]
assert a["confidence"] > 0.8, a
assert a["routing"] == "block", a
assert a["danger"] >= SEVERE, a
ok(f"A: 4 devices agreeing -> {a['danger_name']}, conf {a['confidence']}, blocks roads")

# B: one lonely report -> a rumour, must not block
b = zones["B"]
assert b["confidence"] < CONFIRM_THRESHOLD, b
assert b["routing"] != "block", b
ok(f"B: single report -> conf {b['confidence']}, does NOT block ('{b['routing']}')")

# C: three devices but all hours old -> decay drags it under
c = zones["C"]
assert c["confidence"] < CONFIRM_THRESHOLD, c
ok(f"C: 3 devices but {c['newest_age_hours']} h old -> conf {c['confidence']}, decayed")

# D: five reports, one device -> still one voice
d_ = zones["D"]
assert d_["report_count"] == 5 and d_["device_count"] == 1, d_
assert d_["confidence"] < CONFIRM_THRESHOLD, d_
assert d_["routing"] != "block", d_
ok(f"D: 5 reports from 1 device -> conf {d_['confidence']}, still not confirmed")


# ---------------------------------------------------- scene contradiction
print("\nscene: one report contradicts four")
scene = fakedata.scene_contradiction(NOW)
res = build_danger_map(scene["reports"], NOW)
show(res)

assert res["stats"]["clusters"] == 1, res["stats"]
z = res["zones"][0]
assert z["danger"] >= SEVERE, z
ok(f"zone stands at {z['danger_name']}, conf {z['confidence']}")

held_ids = [h["report_id"] for h in res["held"]]
assert "LIAR" in held_ids, res["held"]
ok("the contradicting report is HELD, not applied")
print("        reason: " + [h for h in res["held"] if h["report_id"] == "LIAR"][0]["reason"])

assert z["routing"] == "block", z
ok("the road stays blocked despite the 'all clear' report")


# ----------------------------------------------------------- scene aerial
print("\nscene: drone survey outweighs older ground reports")
scene = fakedata.scene_aerial(NOW)
res = build_danger_map(scene["reports"], NOW)
show(res)

z = res["zones"][0]
assert z["has_aerial"], z
assert z["danger"] >= SEVERE, z
ok(f"fresh aerial pulls the zone to {z['danger_name']} over older 'knee deep'")
assert z["confidence"] > CONFIRM_THRESHOLD, z
ok(f"aerial can confirm alone: conf {z['confidence']}")


# -------------------------------------------------------------- decay
print("\ndecay over time (same reports, clock moved forward)")
scene = fakedata.scene_basic(NOW)
for hours in (0, 3, 6, 12):
    later = NOW + hours * 3_600_000
    r = build_danger_map(scene["reports"], later)
    a = [z for z in r["zones"] if z["report_ids"][0].startswith("A")]
    conf = a[0]["confidence"] if a else 0.0
    route = a[0]["routing"] if a else "gone"
    print(f"        +{hours:2} h   conf {conf:.2f}   {route}")

r0 = build_danger_map(scene["reports"], NOW)
r12 = build_danger_map(scene["reports"], NOW + 12 * 3_600_000)
c0 = [z for z in r0["zones"] if z["report_ids"][0].startswith("A")][0]["confidence"]
c12 = [z for z in r12["zones"] if z["report_ids"][0].startswith("A")]
c12 = c12[0]["confidence"] if c12 else 0.0
assert c12 < c0, (c0, c12)
ok(f"confidence falls with age: {c0} -> {c12}")


# --------------------------------------------------------- danger vs time
print("\ndanger does NOT rise with silence")
d0 = [z for z in r0["zones"] if z["report_ids"][0].startswith("A")][0]["danger"]
later = build_danger_map(scene["reports"], NOW + 8 * 3_600_000)
d8 = [z for z in later["zones"] if z["report_ids"][0].startswith("A")]
d8 = d8[0]["danger"] if d8 else 0
assert d8 <= d0, (d0, d8)
ok(f"after 8 h of silence danger is {DANGER_NAMES[d8]}, not worse than {DANGER_NAMES[d0]}")
ok("silence lowers certainty, it does not invent danger")


# ------------------------------------------------------------- load test
print("\nload: 200 reports")
scene = fakedata.scene_load(200, NOW)
t0 = time.time()
res = build_danger_map(scene["reports"], NOW)
ms = (time.time() - t0) * 1000
print(f"        {res['stats']}")
ok(f"built the map in {ms:.0f} ms")
assert ms < 2000, ms

print("\nALL CHECKS PASSED\n")

# ------------------------------------------------------ realistic benchmark
print("\nscene: realistic correlated district")
scene = fakedata.scene_realistic(n=240, incidents=12, now=NOW, seed=2026)
res = build_danger_map(scene["reports"], NOW)
truth_incidents = scene["truth"]["incidents"]

# Map each generated report to its hidden incident. This information exists only
# in the benchmark truth, never in the report payload seen by the algorithm.
truth_by_report = {
    rid: incident["incident_id"]
    for incident in truth_incidents
    for rid in incident["report_ids"]
}

# Anti-cheating checks: hidden incident membership must exist only in the
# separate truth structure. Reports themselves may contain IDs and device IDs,
# but neither may encode the hidden incident index. The clustering code receives
# only scene["reports"].
assert all("incident_id" not in r for r in scene["reports"])
assert all(not str(r["id"]).startswith("R") for r in scene["reports"])
assert all("real-dev-" not in str(r["device_id"]) for r in scene["reports"])

zone_incidents = []
for z in res["zones"]:
    ids = {truth_by_report[rid] for rid in z["report_ids"]}
    zone_incidents.append(ids)

# A merge is a produced zone containing reports from multiple hidden incidents.
merges = [ids for ids in zone_incidents if len(ids) > 1]

# A split is a hidden incident represented by more than one produced zone.
incident_zone_counts = {i["incident_id"]: 0 for i in truth_incidents}
for ids in zone_incidents:
    for incident_id in ids:
        incident_zone_counts[incident_id] += 1
splits = [incident_id for incident_id, count in incident_zone_counts.items() if count > 1]

# A hidden incident is recovered when all of its non-held reports that made it
# into a zone landed in the same zone. Held contradictory observations are
# intentionally allowed to be absent from the final zone.
held_ids = {h["report_id"] for h in res["held"]}
recovered = 0
for incident in truth_incidents:
    expected = set(incident["report_ids"]) - held_ids
    containing = [ids for z, ids in zip(res["zones"], zone_incidents)
                  if expected & set(z["report_ids"])]
    if expected and len(containing) == 1:
        recovered += 1

print(f"        reports={len(scene['reports'])}  truth incidents={len(truth_incidents)}")
print(f"        produced zones={len(res['zones'])}  merges={len(merges)}  splits={len(splits)}")
print(f"        incidents recovered={recovered}/{len(truth_incidents)}")
print(f"        held observations={len(held_ids)}")

assert len(merges) == 0, f"false merge(s): {merges}"
assert len(splits) == 0, f"false split(s): {splits}"
assert recovered == len(truth_incidents), (recovered, len(truth_incidents))
ok("realistic correlated incidents remain separate and recoverable")
