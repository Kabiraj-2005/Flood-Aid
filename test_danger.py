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

# Pinned, not time.time(). The scenes below only ever use ages relative to
# `now`, so the absolute value shouldn't matter mathematically — but a wall
# clock made the realistic-benchmark held-report count flaky between runs
# (see danger.py's freshness curve), and a fixed constant makes every run
# byte-for-byte identical instead of merely "usually" identical.
NOW = 1_735_000_000_000  # 2024-12-24T00:26:40Z, arbitrary but fixed
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

# Anti-cheating checks: hidden incident membership must exist only in the
# separate truth structure — never as a field, an id prefix, or a substring
# of an id/device_id the algorithm can see. The clustering code receives
# only scene["reports"].
incident_ids = {i["incident_id"] for i in truth_incidents}
assert all("incident_id" not in r for r in scene["reports"])
assert all(not str(r["id"]).startswith("R") for r in scene["reports"])
assert all("real-dev-" not in str(r["device_id"]) for r in scene["reports"])
assert all(not any(iid in str(r["id"]) for iid in incident_ids)
           for r in scene["reports"])
assert all(not any(iid in str(r["device_id"]) for iid in incident_ids)
           for r in scene["reports"])
ok("no report carries a hidden incident id, index, or marker")

# Score by geometry only: does a produced zone's footprint (its centroid and
# radius, both taken straight from res["zones"]) contain a hidden incident's
# true center? This never looks at report ids or the truth's report_ids
# lists — only at lat/lon, exactly like a human checking the map would.
# zone radius already includes CLUSTER_RADIUS_M; SLACK_M (see
# fakedata.score_realistic) adds a little more for centroid drift from
# noisy/held reports.
score = fakedata.score_realistic(scene, res)

print(f"        reports={len(scene['reports'])}  truth incidents={score['total']}")
print(f"        produced zones={len(res['zones'])}  merges={score['merges']}  splits={score['splits']}")
print(f"        incidents recovered={score['recovered']}/{score['total']}")
print(f"        held observations={score['held']}")

assert score["merges"] == 0, f"false merge(s): {score['merges']}"
assert score["splits"] == 0, f"false split(s): {score['splits']}"
assert score["recovered"] == score["total"], (score["recovered"], score["total"])
ok("realistic correlated incidents remain separate and recoverable")
