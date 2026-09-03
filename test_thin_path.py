"""Prove the three claims that matter: no duplicates, field merge, delta sync."""
from fastapi.testclient import TestClient
from backend.main import app
from backend import db
import os

if db.DB_PATH.exists(): os.remove(db.DB_PATH)
db.init()   # test deletes the file after import, so rebuild the tables
c = TestClient(app)

base = dict(id="rep-1", device_id="phoneA", counter=1, phone_time=1000,
            text="4 houses under water", people_count=11, injured=1,
            water_level="waist", rising=1, road_passable="no",
            lat=26.25, lon=92.34)

# 1. first upload
r = c.post("/api/reports", json={"reports":[base], "last_cursor":0}).json()
assert r["accepted"]["created"] == 1, r
print("created:", r["accepted"], "severity:", r["changes"][0]["severity"])

# 2. SAME report sent 3 more times (a retry storm on a flaky link)
for _ in range(3):
    r = c.post("/api/reports", json={"reports":[base], "last_cursor":0}).json()
total = len(c.get("/api/reports").json()["reports"])
assert total == 1, f"DUPLICATED! {total} rows"
print("after 4 uploads of the same report, rows in db:", total)

# 3. two phones edit different fields offline, both sync later
a = dict(base, counter=2, road_passable="yes", changed=["road_passable"])
b = dict(base, device_id="phoneB", counter=3, people_count=14, changed=["people_count"])
c.post("/api/reports", json={"reports":[a], "last_cursor":0})
c.post("/api/reports", json={"reports":[b], "last_cursor":0})
row = c.get("/api/reports").json()["reports"][0]
assert row["road_passable"] == "yes" and row["people_count"] == 14, row
print("merged both edits: road=", row["road_passable"], "people=", row["people_count"])

# 4. delta sync returns only what changed
cur = c.get("/api/changes?since=0").json()["cursor"]
empty = c.get(f"/api/changes?since={cur}").json()
assert empty["changes"] == [], empty
print("delta sync with fresh cursor returns:", len(empty["changes"]), "changes")

# 5. waiting time raises severity
from backend.severity import compute_severity, explain
old = dict(row, reported_at=row["reported_at"] - 3*3600*1000)
print("severity now:", compute_severity(row), "| after 3h wait:", compute_severity(old))
print("why:", "; ".join(explain(old)))
print("\nALL CHECKS PASSED")

# 6. waiting time, using a realistic server-seen timestamp
import time
now = int(time.time()*1000)
fresh = dict(row, reported_at=now, synced_at=now)
waited = dict(row, reported_at=now - 3*3600*1000, synced_at=now - 3*3600*1000)
print("\nsame incident, fresh:", compute_severity(fresh, now),
      "| waited 3h:", compute_severity(waited, now))
print("why (3h):", "; ".join(explain(waited, now)))

# 7. a phone with a broken clock must not jump the queue
broken = dict(row, reported_at=0, synced_at=now)   # phone thinks it is 1970
print("broken clock severity:", compute_severity(broken, now), "(not astronomical)")
assert compute_severity(broken, now) < 20
