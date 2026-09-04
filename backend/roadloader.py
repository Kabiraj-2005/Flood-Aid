"""
Load a RoadGraph from OpenStreetMap data fetched by scripts/fetch_roads.py.

The file on disk is raw Overpass JSON (a list of "node" and "way"
elements). This module is the only place that knows that shape — routing.py
only ever sees a RoadGraph, exactly as it does for the synthetic
grid_town() graph. Swapping the data source means changing
backend/main.py's _road_graph() to call load_osm() instead of grid_town(),
and nothing in routing.py.

Reads a file on disk. Never touches the network — see
scripts/fetch_roads.py's docstring for why.
"""

import json
from collections import deque
from pathlib import Path

from .routing import RoadGraph

# The one committed OSM extract the app ships with. A single constant here
# so backend/main.py and scripts/seed_demo.py can never point at two
# different files without saying so explicitly.
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "morigaon_roads.json"

# OSM highway tag -> routing.py's road_type, which DEFAULT_SPEED_KMH keys
# off. Anything not listed here (there shouldn't be any, since
# fetch_roads.py only queries these eight types) is skipped rather than
# guessed at.
HIGHWAY_TO_ROAD_TYPE = {
    "motorway": "highway",
    "trunk": "highway",
    "primary": "main",
    "secondary": "main",
    "tertiary": "residential",
    "unclassified": "residential",
    "residential": "residential",
    "track": "track",
}

# Real OSM extracts contain orphaned fragments — a driveway clipped by the
# bounding box, a footbridge digitised as its own disconnected way. If a
# safe zone or a report snaps onto a three-node island, routing silently
# fails ("no route") for a reason that has nothing to do with flooding. Keep
# only the largest connected component when it holds most of the network.
MIN_LARGEST_COMPONENT_FRACTION = 0.90


def connected_components(graph):
    """All connected components, as a list of node-id sets, largest first.

    Undirected BFS over graph.edges — the same adjacency routing.py's A*
    walks, so "connected" here means exactly what it means to find_route().
    """
    unseen = set(graph.nodes)
    components = []
    while unseen:
        start = next(iter(unseen))
        comp = {start}
        queue = deque([start])
        unseen.discard(start)
        while queue:
            node = queue.popleft()
            for neighbour, _key in graph.edges.get(node, []):
                if neighbour in unseen:
                    unseen.discard(neighbour)
                    comp.add(neighbour)
                    queue.append(neighbour)
        components.append(comp)
    components.sort(key=len, reverse=True)
    return components


def _largest_component_subgraph(graph, keep):
    """A new RoadGraph containing only nodes in `keep` and edges between them."""
    trimmed = RoadGraph()
    for nid in keep:
        lat, lon = graph.nodes[nid]
        trimmed.add_node(nid, lat, lon)
    seen_edges = set()
    for key, meta in graph.edge_meta.items():
        a, b = key
        if a not in keep or b not in keep or key in seen_edges:
            continue
        seen_edges.add(key)
        trimmed.add_edge(a, b, road_type=meta["road_type"])
    return trimmed


def load_osm(path):
    """
    Build a RoadGraph from an Overpass JSON export.

    Nodes with no surviving edge (every way through them used an excluded
    highway type, or was malformed) are left out — a node routing can never
    reach is not part of the road network for our purposes.
    """
    with open(path) as f:
        data = json.load(f)

    elements = data["elements"]
    coords = {}
    for el in elements:
        if el["type"] == "node":
            coords[el["id"]] = (el["lat"], el["lon"])

    graph = RoadGraph()
    added_nodes = set()
    skipped_unknown_highway = 0
    skipped_missing_coords = 0

    for el in elements:
        if el["type"] != "way":
            continue
        highway = (el.get("tags") or {}).get("highway")
        road_type = HIGHWAY_TO_ROAD_TYPE.get(highway)
        if road_type is None:
            skipped_unknown_highway += 1
            continue

        node_ids = el.get("nodes", [])
        for osm_id in node_ids:
            if osm_id in added_nodes:
                continue
            if osm_id not in coords:
                skipped_missing_coords += 1
                continue
            lat, lon = coords[osm_id]
            graph.add_node(str(osm_id), lat, lon)
            added_nodes.add(osm_id)

        for a, b in zip(node_ids, node_ids[1:]):
            if a not in coords or b not in coords:
                continue
            graph.add_edge(str(a), str(b), road_type=road_type)

    total_nodes = len(graph.nodes)
    components = connected_components(graph)
    largest = components[0] if components else set()
    fraction = (len(largest) / total_nodes) if total_nodes else 0.0

    print(f"load_osm: {total_nodes} nodes, {len(graph.edge_meta)} edges "
          f"from {path}")
    if skipped_unknown_highway:
        print(f"load_osm: skipped {skipped_unknown_highway} way(s) with an "
              f"unmapped highway tag")
    print(f"load_osm: largest connected component is {len(largest)} of "
          f"{total_nodes} nodes ({fraction:.1%})")

    if fraction < MIN_LARGEST_COMPONENT_FRACTION and total_nodes:
        print(f"load_osm: below {MIN_LARGEST_COMPONENT_FRACTION:.0%} — "
              f"dropping {len(components) - 1} smaller fragment(s), "
              f"keeping only the largest component")
        graph = _largest_component_subgraph(graph, largest)

    return graph
