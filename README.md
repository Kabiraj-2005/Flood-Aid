# FloodAid — working model, step 1

The thin path: a report is filed with no network, held on the phone,
uploaded by itself when signal returns, and appears in the control room.

Nothing else matters until this runs. Build on top of it, not beside it.

## Run

    pip install fastapi uvicorn python-multipart
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Open http://localhost:8000 on your laptop, or
http://<your-laptop-ip>:8000 on a phone connected to the same wifi.

## Try the thing that matters

1. Open the app, fill a report, press Save. It appears under "Waiting to upload".
2. Press "Simulate going offline". File two more. They queue.
3. Press "Simulate coming back online". Watch the queue empty.
4. `curl localhost:8000/api/reports` — they are all there, once each.

Then do it for real: put the phone in airplane mode instead of pressing
the button. That is the demo.

## Test

    python3 test_thin_path.py

Checks that the same report uploaded four times creates one row, that two
phones editing different fields offline both keep their change, that delta
sync returns nothing when the cursor is current, and that a phone with a
broken clock cannot jump the queue.

## Files

    backend/db.py        the agreed report schema. Do not rename a column
                         without telling the whole team.
    backend/main.py      upload (idempotent), delta sync, merge, list
    backend/severity.py  the visible severity formula
    web/outbox.js        the offline queue. This file is the project.
    web/index.html       the field report form

## Two bugs already found and fixed

Keep these in mind, they will come up in Q&A:

1. **Phone clocks lie.** Waiting time was computed from the phone's own
   timestamp, so a device with a wrong clock scored as having waited for
   decades and would have starved every real incident. Waiting now starts
   no earlier than the moment the server first saw the report, and is
   capped at 24 hours.

2. **A stale copy silently undid a fix.** Both phones send the whole
   record, so the server could not tell "I did not touch this field" from
   "I set it back to the old value". Phones now name the fields they
   actually edited.

## Next, in this order

3. clustering + confidence + decay
4. contradiction hold
5. zones -> remove crossing roads -> route
6. dispatch with capacity and return legs
7. drone polygon ingest
8. polish

## Languages

The interface runs in English, Assamese, Bengali and Hindi. All strings are
in `web/i18n.js` and ship inside the app, so switching language works with
no network — there is no translation service to call during a flood.

**Before the demo:** the Assamese, Bengali and Hindi strings were written
without a native speaker. Get one to read every line, fix what is wrong,
then set that language to `true` in `VERIFIED` at the top of the file.
Until you do, the app shows a strip saying the translation is unchecked.
Leave that strip in — a wrong word on "road passable" is worse than English.

Report *text* is separate from interface language. People write in whatever
mix they use, and the server extraction handles it.

## The danger map

`backend/danger.py` turns reports into zones. Three separate ideas, kept
separate on purpose:

- **Clustering** — which reports are about the same place (150 m, single-link)
- **Danger** — how bad it is, 5 levels, from what reports SAY
- **Confidence** — how sure we are, from agreement and age

**Danger does not rise with silence.** A zone that goes quiet becomes less
certain, not more dangerous. An area with no reports is UNKNOWN — we do not
colour it, because we do not claim to know what nobody has told us.

Levels: safe / caution (ankle) / restricted (knee) / severe (waist) /
red (above waist or rising fast).

Routing outcome per zone: `block` (confident and fresh), `expensive` (5x cost,
used only if nothing else), `ignore`.

Tuning constants live at the top of the file and nowhere else:
`CLUSTER_RADIUS_M`, `CONFIDENCE_HALF_LIFE_H`, `CONFIRM_THRESHOLD`,
`CORROBORATION_CAP`, `STALE_HOURS`.

    python3 test_danger.py        # scores the map against known answers
    python3 -m backend.fakedata   # print a scene

Endpoints: `GET /api/danger`, `GET /api/reports/{id}/why`

### Three more bugs found while building this

3. **One device could close a road.** A single fresh report reached
   confidence 0.66 and blocked roads on its own. Added `CORROBORATION_CAP`:
   one device tops out at 0.45, two at 0.75. One person filing five times is
   still one person. Drone surveys are exempt — direct observation.

4. **A held report still changed the map.** Contradiction detection ran
   after the danger level was computed, so the "all clear" report had
   already dragged the weighted average down and demoted the zone before
   being held. Now two passes: provisional level, find contradictions,
   recompute with those excluded.

5. **Freshness was buying immunity.** The hold rule tested report *weight*,
   so a very recent lone "all clear" sailed through. Now it tests
   *corroboration* — how many other devices back that claim. Being recent is
   not the same as being right.

### Known rough edge

On the random load scene, 26% of reports get held for review. That is an
artifact of the generator picking water levels at random within a cluster;
real reports of the same place correlate far more. Do not tune the
thresholds against that number — build a more realistic scene first.

## Routing

`backend/routing.py`. A road network is a graph, a danger zone is a circle.
Before searching we check every edge against every zone:

- `block` — the edge is removed entirely
- `expensive` — kept but 5x cost, used only if there is genuinely nothing else
- `ignore` — untouched

Then A* on what is left, with travel time as the cost.

The `expensive` case matters. A hard yes/no means that on a bad day, when
every way out crosses some uncertain zone, we return "no route" and help
nobody. A person surrounded by water needs the least bad option with an
honest label, not an error.

Every route carries its evidence: which zones it avoided, whether it crosses
anything unconfirmed, and how old that evidence is.

    python3 test_routing.py

Current results on the synthetic grid:

    routes through confirmed water — naive: 18, ours: 0
    average detour cost: 11.1% more travel time
    0.3 ms per route

Endpoint: `GET /api/route?lat=..&lon=..&mode=drive`

`grid_town` (fakedata.py) is still the correctness fixture — `test_routing.py`
tests against it directly, unchanged, because its scenes have known answers.
The app itself routes on real roads; see "Real roads: Morigaon district"
below.

### Two more bugs found while building this

6. **The detour scene proved nothing.** It used a plain grid, where every
   staircase path between two corners is the same length. The naive router
   was never forced through the flooded block — it routed around by
   accident and the test passed for the wrong reason. Fixed by making the
   middle row a fast road, so ignoring flooding genuinely is faster.

7. **The benchmark made avoiding floods look free.** It compared distance,
   and our route takes slower back streets that are shorter in metres — so
   the "detour cost" came out at -1.5%, as if avoiding water were a bonus.
   Both routers optimise travel time, so time is the honest comparison.
   It is +11.1%. There is now an assertion that the figure can never be
   negative.

## Real roads: Morigaon district

`grid_town` was always a stand-in. The app now routes on the actual road
network of Morigaon district, Assam — OpenStreetMap data, fetched once and
committed, never fetched live (see CLAUDE.md: works with the network off).

    python3 scripts/fetch_roads.py      # developer step, run occasionally — not at runtime
    python3 test_osm.py                 # sanity-checks the committed extract

**Fetching.** `scripts/fetch_roads.py` queries Overpass for eight highway
types (motorway/trunk/primary/secondary/tertiary/unclassified/residential/
track — footway/cycleway/path/service excluded) in a box centred on
Morigaon town, and saves the raw result to `data/morigaon_roads.json`. A
whole-district box returns ~138k nodes, well over the ~30k budget a phone
should hold, so the script starts at a 13 km half-width and shrinks by 20%
until the count fits:

    attempt 1: half-width 13.00 km -> 35,725 nodes (too many)
    attempt 2: half-width 10.40 km -> 24,778 nodes  (kept)

**Loading.** `backend/roadloader.py`'s `load_osm(path)` turns that JSON into
the same `RoadGraph` `grid_town()` builds, mapping OSM's `highway` tag onto
`routing.py`'s `road_type` (motorway/trunk -> highway, primary/secondary ->
main, tertiary/unclassified/residential -> residential, track -> track).
`backend/main.py`'s `_road_graph()` calls it; the A* search and the
zone-vs-edge logic in `routing.py` did not need to change at all — the only
thing that did was `nearest_node` (below), for speed, not correctness.

Real extracts are not one clean component — a driveway clipped by the
bounding box, a footbridge digitised on its own, and a start or goal
snapping onto one silently fails to route for a reason that has nothing to
do with flooding. `load_osm` checks the largest connected component and
keeps only it when that is under 90% of all nodes.

    24,778 nodes, 25,192 edges, loaded in 73 ms
    largest connected component: 23,722 of 24,778 nodes (95.7%) — above the
    90% floor, so nothing was trimmed

**Performance.** `RoadGraph.nearest_node` used to scan every node — fine at
`grid_town`'s 81, not at 25k, and it runs once per safe zone on every
`/api/route` call. It now buckets nodes on a ~500 m grid and expands ring by
ring from the target bucket until the closest candidate found is provably
closer than anything an unsearched ring could hold (not just "until a ring
is non-empty" — real road data is uneven enough that the first non-empty
3x3 block can still miss a genuinely closer node one ring further out).

    nearest_node, 50 random points: 8.4 ms/call brute force -> 0.18-0.3 ms/call bucketed
       (all 50 agree with brute force exactly)
    full route_to_safety (1 start + 3 safe zones = 4 nearest_node calls
       + A*), 20 random starts: 44.5 ms/route brute force -> 11.5 ms/route bucketed

**Payload size.** `/api/roads` (nodes + edges, ~1.6 MB at this scale) does
not change while the server is up, so the control room fetches it once. What
*does* change every few seconds — which edges the current danger map blocks
or penalises — is now its own endpoint, `/api/roads/blocked` (~9 KB), which
is what the 5s poll actually re-fetches.

**Seeding.** `scripts/seed_demo.py --incidents 12` (the default) places
danger zones on real Morigaon roads instead of the old synthetic grid, and
`verify_zones_on_roads()` still asserts at least half of them intersect an
edge before the demo is allowed to proceed:

    12 confirmed danger zone(s), 12 of them touch the road network
    325 of 25,192 roads removed by confirmed flooding

Endpoints: `GET /api/roads`, `GET /api/roads/blocked`

    python3 test_osm.py

Checks the extract loads non-empty, `nearest_node` agrees with brute force
on 50 random points, a route between two random connected nodes completes
in under 100 ms, and — the one that matters for the "routes around water"
claim on real, non-grid geometry — dropping a danger zone on a route's
midpoint forces a genuinely different path that crosses that zone zero
times.
