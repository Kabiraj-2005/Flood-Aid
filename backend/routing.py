"""
Routing that knows where the water is.

This is claim two: we route around water instead of through it.

The idea is small. A road network is a graph. A danger zone is a circle on
the map. Before searching for a path we look at every edge and ask whether
it crosses a zone:

    block      -> remove the edge entirely
    expensive  -> keep it, multiply its cost, so it is used only if there
                  is genuinely nothing else
    ignore     -> leave it alone

Then run A* on what is left.

The `expensive` case matters more than it looks. A hard yes/no would mean
that on a bad day, when every route out crosses some uncertain zone, we
return "no route" and help nobody. A person surrounded by water needs the
least bad option and an honest label on it, not an error.
"""

import heapq
import math
from .danger import haversine_m

# --------------------------------------------------------------- tuning

UNCERTAIN_COST_MULTIPLIER = 5.0   # cost of crossing an unconfirmed zone
WALK_SPEED_KMH = 4.0
DEFAULT_SPEED_KMH = {
    "highway": 60.0,
    "main": 40.0,
    "residential": 25.0,
    "track": 12.0,
    "footpath": WALK_SPEED_KMH,
}


class RoadGraph:
    """
    Nodes are (lat, lon). Edges are two-way by default.

    Deliberately plain. When we swap in real OpenStreetMap data, only the
    loader changes — everything below keeps working.
    """

    def __init__(self):
        self.nodes = {}                  # id -> (lat, lon)
        self.edges = {}                  # id -> [(neighbour_id, edge_key)]
        self.edge_meta = {}              # edge_key -> {length_m, road_type}
        self._buckets = None              # built lazily, invalidated on add_node

    def add_node(self, node_id, lat, lon):
        self.nodes[node_id] = (lat, lon)
        self.edges.setdefault(node_id, [])
        self._buckets = None

    def add_edge(self, a, b, road_type="residential", two_way=True):
        la, lo_a = self.nodes[a]
        lb, lo_b = self.nodes[b]
        length = haversine_m(la, lo_a, lb, lo_b)
        key = tuple(sorted((a, b)))
        self.edge_meta[key] = {"length_m": length, "road_type": road_type}
        self.edges[a].append((b, key))
        if two_way:
            self.edges[b].append((a, key))

    def travel_seconds(self, edge_key, mode="drive"):
        meta = self.edge_meta[edge_key]
        if mode == "walk":
            kmh = WALK_SPEED_KMH
        else:
            kmh = DEFAULT_SPEED_KMH.get(meta["road_type"], 25.0)
        return meta["length_m"] / (kmh * 1000 / 3600)

    # A ~500 m grid cell. Only used to bucket nodes for nearest_node — not
    # exact, doesn't need to be; it just has to keep each bucket small.
    _BUCKET_M = 500.0

    def _bucket_steps(self):
        """Degrees-per-bucket for lat and lon, sized to _BUCKET_M.

        Longitude degrees shrink towards the poles, but the network here
        spans a single district — one reference latitude (the mean) is
        close enough for every node in it.
        """
        lats = [lat for lat, _ in self.nodes.values()]
        mean_lat = sum(lats) / len(lats)
        lat_step = self._BUCKET_M / 111_320.0
        lon_step = self._BUCKET_M / (111_320.0 * max(math.cos(math.radians(mean_lat)), 1e-6))
        return lat_step, lon_step

    def _bucket_key(self, lat, lon, lat_step, lon_step):
        return (int(lat // lat_step), int(lon // lon_step))

    def _ensure_buckets(self):
        if self._buckets is not None:
            return
        if not self.nodes:
            self._buckets = ({}, 1.0, 1.0)
            return
        lat_step, lon_step = self._bucket_steps()
        buckets = {}
        for nid, (lat, lon) in self.nodes.items():
            key = self._bucket_key(lat, lon, lat_step, lon_step)
            buckets.setdefault(key, []).append(nid)
        self._buckets = (buckets, lat_step, lon_step)

    def nearest_node(self, lat, lon):
        """
        Snap a position to the closest node on the network.

        A linear scan is fine at grid_town's 81 nodes and far too slow at
        OSM scale — this runs once per safe zone on every /api/route call.
        Nodes are bucketed on a ~500 m grid; we start from the target
        bucket and its eight neighbours and widen outward one ring at a
        time.

        Real OSM data is not evenly spaced like the synthetic grid, so
        "widen only if the 3x3 block is empty" is not enough: a block can
        have one candidate node in a corner while a genuinely closer node
        sits just outside it, in the next ring out. So instead we keep
        expanding until the closest candidate found so far is provably
        nearer than anything an unsearched ring could contain — after
        fully searching out to ring R, any unsearched bucket is at least
        R * _BUCKET_M away, so once best_d <= R * _BUCKET_M no wider ring
        can beat it.
        """
        self._ensure_buckets()
        buckets, lat_step, lon_step = self._buckets
        if not self.nodes:
            return None, float("inf")

        bi, bj = self._bucket_key(lat, lon, lat_step, lon_step)
        best, best_d = None, float("inf")
        searched = set()
        ring = 1
        max_ring = 40   # ~20 km out; beyond this a full scan is cheaper than widening further

        while ring <= max_ring:
            cells = [(bi + di, bj + dj)
                     for di in range(-ring, ring + 1)
                     for dj in range(-ring, ring + 1)]
            for cell in cells:
                if cell in searched:
                    continue
                searched.add(cell)
                for nid in buckets.get(cell, []):
                    nlat, nlon = self.nodes[nid]
                    d = haversine_m(lat, lon, nlat, nlon)
                    if d < best_d:
                        best, best_d = nid, d

            if best is not None and best_d <= ring * self._BUCKET_M:
                break
            ring += 1

        if best is None:
            # Nothing within max_ring at all — a point far outside the
            # network's extent. Fall back to a full scan rather than
            # returning nothing.
            for nid, (nlat, nlon) in self.nodes.items():
                d = haversine_m(lat, lon, nlat, nlon)
                if d < best_d:
                    best, best_d = nid, d

        return best, best_d


# ------------------------------------------------------- zones vs edges

def _segment_point_distance_m(a, b, centre):
    """
    Distance in metres from the closest point on segment a-b to centre.

    We work in metres by projecting onto a local flat plane, which is fine
    at these distances — over a few kilometres the error is centimetres.
    """
    clat, clon = centre
    mlat = math.radians(clat)

    def to_m(p):
        return ((p[1] - clon) * 111_320.0 * math.cos(mlat),
                (p[0] - clat) * 111_320.0)

    ax, ay = to_m(a)
    bx, by = to_m(b)

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)

    # how far along the segment the closest point sits, clamped to [0,1]
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py)


def _segment_hits_circle(a, b, centre, radius_m):
    """Does the road segment a-b pass within radius_m of centre?"""
    return _segment_point_distance_m(a, b, centre) <= radius_m


def zones_touching_roads(graph, zones):
    """Which of these zones actually intersect at least one road edge.

    A zone can be confirmed and drawn and still touch nothing on the map —
    that is exactly the "danger data and road network live in different
    places" bug this exists to catch. Used by the seed script so that bug
    fails loudly instead of quietly making the routing demo meaningless.
    """
    edges = [(graph.nodes[a], graph.nodes[b]) for a, b in graph.edge_meta]
    return [z for z in zones
            if any(_segment_hits_circle(a, b, (z["lat"], z["lon"]), z["radius_m"])
                   for a, b in edges)]


def apply_zones(graph, zones):
    """
    Work out what each edge costs given the current danger map.

    Returns:
      blocked    set of edge keys to remove entirely
      penalties  edge key -> multiplier for edges we keep but discourage
      why        edge key -> the zone that caused it, so the UI can explain

    An edge hit by several zones takes the worst outcome.
    """
    blocked, penalties, why = set(), {}, {}

    for key, meta in graph.edge_meta.items():
        a_id, b_id = key
        a, b = graph.nodes[a_id], graph.nodes[b_id]

        for z in zones:
            if z["routing"] == "ignore":
                continue
            if not _segment_hits_circle(a, b, (z["lat"], z["lon"]),
                                        z["radius_m"]):
                continue

            if z["routing"] == "block":
                blocked.add(key)
                why[key] = z
                penalties.pop(key, None)
                break                       # nothing worse than blocked
            else:
                if key not in penalties:
                    penalties[key] = UNCERTAIN_COST_MULTIPLIER
                    why[key] = z

    return blocked, penalties, why


# ------------------------------------------------------------------ A*

def find_route(graph, start_id, goal_ids, zones=(), mode="drive",
               allow_uncertain=True, _zone_effects=None):
    """
    Cheapest path from start to the NEAREST of several goals.

    goal_ids is a set because in practice we want "the closest safe zone
    with space", not one specific building. Searching outward once and
    stopping at the first goal reached is correct and much cheaper than
    running the search once per candidate.

    Returns a dict with the path and, importantly, WHY — which zones were
    avoided, and whether the route crosses anything uncertain. A route
    without its evidence is not something a dispatcher should act on.

    _zone_effects is an internal escape hatch: pass apply_zones(graph,
    zones)'s own return value when a caller already has it and is about to
    call this in a loop with the SAME zones every time (the control room's
    "find a demo route" does — see /api/route/demo). apply_zones is
    O(edges x zones); at district scale that's real cost (~225ms for 12
    zones over 25k edges) not worth paying per candidate. Every normal
    caller leaves this None and gets exactly the old behaviour.
    """
    goal_ids = set(goal_ids)
    if start_id not in graph.nodes:
        return {"found": False, "reason": "start is not on the road network"}
    if not goal_ids:
        return {"found": False, "reason": "no destination given"}

    blocked, penalties, why = _zone_effects if _zone_effects is not None else apply_zones(graph, zones)

    # A* needs an optimistic guess of the remaining cost. Straight-line
    # distance at the fastest speed can never overestimate, which is what
    # keeps the result optimal.
    fastest = max(DEFAULT_SPEED_KMH.values()) if mode == "drive" else WALK_SPEED_KMH
    fastest_ms = fastest * 1000 / 3600

    def h(node_id):
        lat, lon = graph.nodes[node_id]
        return min(haversine_m(lat, lon, *graph.nodes[g]) / fastest_ms
                   for g in goal_ids)

    open_set = [(h(start_id), 0.0, start_id)]
    came_from = {}
    best_cost = {start_id: 0.0}
    crossed = {}                 # node -> uncertain zones crossed to reach it
    crossed[start_id] = []
    seen = set()

    while open_set:
        _, cost, node = heapq.heappop(open_set)
        if node in seen:
            continue
        seen.add(node)

        if node in goal_ids:
            path = [node]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            path.reverse()
            return _describe(graph, path, cost, crossed[node], why, blocked, mode)

        for neighbour, key in graph.edges.get(node, []):
            if key in blocked:
                continue
            mult = penalties.get(key, 1.0)
            if mult > 1.0 and not allow_uncertain:
                continue

            step = graph.travel_seconds(key, mode) * mult
            new_cost = cost + step
            if new_cost < best_cost.get(neighbour, float("inf")):
                best_cost[neighbour] = new_cost
                came_from[neighbour] = node
                crossed[neighbour] = crossed[node] + (
                    [why[key]] if mult > 1.0 else [])
                heapq.heappush(open_set, (new_cost + h(neighbour),
                                          new_cost, neighbour))

    # Nowhere left to go. This is a real answer, not an error — say it
    # plainly and let the caller escalate the person as an incident.
    return {
        "found": False,
        "reason": "every route out crosses a confirmed danger zone",
        "blocked_edges": len(blocked),
    }


def _describe(graph, path, cost_s, uncertain_zones, why, blocked, mode):
    """Build the answer, including the evidence a dispatcher needs."""
    metres = 0.0
    for a, b in zip(path, path[1:]):
        metres += graph.edge_meta[tuple(sorted((a, b)))]["length_m"]

    uniq = {z["cluster_id"]: z for z in uncertain_zones}
    oldest = max((z["newest_age_hours"] for z in uniq.values()), default=None)

    if uniq:
        evidence = (
            f"crosses {len(uniq)} unconfirmed zone(s); "
            f"newest supporting report {oldest} h old"
        )
        confidence = "uncertain"
    else:
        evidence = "avoids every confirmed danger zone"
        confidence = "clear"

    return {
        "found": True,
        "path": path,
        "coordinates": [graph.nodes[n] for n in path],
        "distance_m": round(metres, 1),
        "travel_seconds": round(cost_s, 1),
        "travel_minutes": round(cost_s / 60, 1),
        "mode": mode,
        "confidence": confidence,
        "crosses_uncertain": [
            {"cluster_id": z["cluster_id"], "danger": z["danger_name"],
             "age_hours": z["newest_age_hours"]} for z in uniq.values()
        ],
        "roads_removed": len(blocked),
        "evidence": evidence,
    }


def route_to_safety(graph, lat, lon, safe_zones, zones=(), mode="drive",
                    _zone_effects=None):
    """
    The call the app actually makes: from a position to the nearest safe
    zone that still has space.

    A safe zone that is full is not a destination. Sending someone to a
    shelter with no room means a second displacement, and that is a real
    failure people have experienced.

    _zone_effects: see find_route — passed straight through for a caller
    that already has apply_zones(graph, zones)'s result and is calling this
    repeatedly with the same zones.
    """
    start, snap_m = graph.nearest_node(lat, lon)
    if start is None:
        return {"found": False, "reason": "no road network loaded"}

    open_zones = [z for z in safe_zones
                  if z.get("status", "open") == "open"
                  and z.get("occupied", 0) < z.get("capacity", 0)]
    if not open_zones:
        return {"found": False,
                "reason": "every known safe zone is full or closed"}

    goal_map = {}
    for z in open_zones:
        nid, _ = graph.nearest_node(z["lat"], z["lon"])
        goal_map.setdefault(nid, z)

    result = find_route(graph, start, set(goal_map), zones, mode,
                        _zone_effects=_zone_effects)
    if result["found"]:
        result["snapped_m"] = round(snap_m, 1)
        result["destination"] = goal_map[result["path"][-1]]
    return result
