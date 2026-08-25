"""Build compact, offline vector layers for the Jeonbuk dashboard map.

The browser bundle contains real SGIS administrative boundaries, selected OSM
major roads, and exact directed shortest-path geometry for every depot/candidate
pair already present in the route matrix.  It deliberately does not publish the
full 1.8M-node road graph; the UI exposes sampled nodes from the active routes.
"""

from __future__ import annotations

import csv
import heapq
import json
import math
from array import array
from collections import defaultdict
from pathlib import Path

import osmium

from build_jeonbuk_route_scenario import load_graph_context
from build_roadnet import PBF


ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_OUT = ROOT / "data" / "processed"
BOUNDARY_FILE = DATA_RAW / "hjd2026.geojson"
SCENARIO_FILE = DATA_OUT / "jeonbuk_route_scenario.json"
ACCESS_FILE = DATA_OUT / "access_road.csv"
OUTPUT = ROOT / "docs" / "demo-jeonbuk" / "map-data.js"

BOUNDARY_TOLERANCE = 0.00035
ROAD_TOLERANCE = 0.00045
ROUTE_TOLERANCE = 0.00018
MAX_NODE_SAMPLE_PER_LEG = 64
ROAD_CLASS = {
    "motorway": "motorway",
    "motorway_link": "motorway",
    "trunk": "trunk",
    "trunk_link": "trunk",
    "primary": "primary",
    "primary_link": "primary",
    "secondary": "secondary",
    "secondary_link": "secondary",
}


def _point_line_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    if start == end:
        return math.dist(point, start)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (
        dx * dx + dy * dy
    )
    ratio = max(0.0, min(1.0, ratio))
    projected = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projected)


def simplify_line(
    points: list[tuple[float, float]], tolerance: float
) -> list[tuple[float, float]]:
    """Iterative Ramer-Douglas-Peucker simplification for an open line."""

    if len(points) <= 2:
        return points
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        maximum = -1.0
        selected = -1
        for index in range(start + 1, end):
            distance = _point_line_distance(points[index], points[start], points[end])
            if distance > maximum:
                maximum = distance
                selected = index
        if selected >= 0 and maximum > tolerance:
            keep.add(selected)
            stack.append((start, selected))
            stack.append((selected, end))
    return [points[index] for index in sorted(keep)]


def simplify_ring(
    points: list[tuple[float, float]], tolerance: float
) -> list[tuple[float, float]]:
    """Simplify a closed ring without collapsing its coincident endpoints."""

    if len(points) <= 5:
        return points
    open_points = points[:-1] if points[0] == points[-1] else points[:]
    if len(open_points) <= 4:
        return [*open_points, open_points[0]]
    pivot = max(
        range(1, len(open_points)),
        key=lambda index: math.dist(open_points[0], open_points[index]),
    )
    left = simplify_line(open_points[: pivot + 1], tolerance)
    right = simplify_line([*open_points[pivot:], open_points[0]], tolerance)
    simplified = [*left[:-1], *right]
    if len(simplified) < 4:
        return points
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return simplified


def rounded(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[round(lon, 6), round(lat, 6)] for lon, lat in points]


def service_zone(sigungu: str) -> str:
    return "전주시" if sigungu.startswith("전주시") else sigungu


def extract_boundaries() -> tuple[list[dict], dict[str, float]]:
    raw = json.loads(BOUNDARY_FILE.read_text(encoding="utf-8"))
    features = [
        feature
        for feature in raw["features"]
        if feature["properties"].get("sido") == "52"
    ]
    if len(features) != 243:
        raise RuntimeError(f"expected 243 Jeonbuk boundaries, got {len(features)}")

    boundaries = []
    all_lons: list[float] = []
    all_lats: list[float] = []
    for feature in sorted(features, key=lambda row: row["properties"]["adm_cd2"]):
        properties = feature["properties"]
        polygons = []
        for polygon in feature["geometry"]["coordinates"]:
            rings = []
            for raw_ring in polygon:
                ring = [(float(lon), float(lat)) for lon, lat in raw_ring]
                all_lons.extend(lon for lon, _ in ring)
                all_lats.extend(lat for _, lat in ring)
                rings.append(rounded(simplify_ring(ring, BOUNDARY_TOLERANCE)))
            polygons.append(rings)
        boundaries.append({
            "code": properties["adm_cd2"],
            "name": properties["adm_nm"].split()[-1],
            "service_zone": service_zone(properties["sggnm"]),
            "polygons": polygons,
        })

    bounds = {
        "min_lon": min(all_lons),
        "max_lon": max(all_lons),
        "min_lat": min(all_lats),
        "max_lat": max(all_lats),
    }
    return boundaries, bounds


class MajorRoadHandler(osmium.SimpleHandler):
    def __init__(self, bounds: dict[str, float]):
        super().__init__()
        self.bounds = bounds
        self.lines: dict[str, list[list[list[float]]]] = defaultdict(list)
        self.way_count = 0

    def way(self, way) -> None:
        road_class = ROAD_CLASS.get(way.tags.get("highway"))
        if not road_class:
            return
        points: list[tuple[float, float]] = []
        for node in way.nodes:
            if node.location.valid():
                points.append((float(node.location.lon), float(node.location.lat)))
        if len(points) < 2:
            return
        margin = 0.025
        min_lon = min(point[0] for point in points)
        max_lon = max(point[0] for point in points)
        min_lat = min(point[1] for point in points)
        max_lat = max(point[1] for point in points)
        if (
            max_lon < self.bounds["min_lon"] - margin
            or min_lon > self.bounds["max_lon"] + margin
            or max_lat < self.bounds["min_lat"] - margin
            or min_lat > self.bounds["max_lat"] + margin
        ):
            return
        line = simplify_line(points, ROAD_TOLERANCE)
        if len(line) >= 2:
            self.lines[road_class].append(rounded(line))
            self.way_count += 1


def extract_major_roads(bounds: dict[str, float]) -> tuple[dict, int]:
    handler = MajorRoadHandler(bounds)
    handler.apply_file(str(PBF), locations=True, idx="flex_mem")
    return {
        road_class: handler.lines.get(road_class, [])
        for road_class in ("motorway", "trunk", "primary", "secondary")
    }, handler.way_count


def _sample_nodes(
    nodes: list[int], lats: array, lons: array, limit: int
) -> list[list[float]]:
    if len(nodes) <= limit:
        selected = nodes
    else:
        indexes = {
            round(index * (len(nodes) - 1) / (limit - 1))
            for index in range(limit)
        }
        selected = [nodes[index] for index in sorted(indexes)]
    return [[round(lons[node], 6), round(lats[node], 6)] for node in selected]


def _paths_to_origins(
    context: dict,
    destination: int,
    origins: set[int],
    distances: array,
) -> tuple[dict[int, list[int]], dict[int, float]]:
    """Recover original-direction shortest paths using the reversed OSM CSR."""

    pending = set(origins)
    pending.discard(destination)
    parent: dict[int, int] = {}
    found_distance = {destination: 0.0}
    touched = [destination]
    distances[destination] = 0.0
    heap = [(0.0, destination)]
    while heap and pending:
        distance, node = heapq.heappop(heap)
        if distance != distances[node]:
            continue
        if node in pending:
            found_distance[node] = distance
            pending.remove(node)
        for position in range(context["offsets"][node], context["offsets"][node + 1]):
            next_node = context["neighbors"][position]
            next_distance = distance + context["weights"][position]
            if next_distance < distances[next_node]:
                if math.isinf(distances[next_node]):
                    touched.append(next_node)
                distances[next_node] = next_distance
                parent[next_node] = node
                heapq.heappush(heap, (next_distance, next_node))
    if pending:
        raise RuntimeError(f"route geometry missing for {len(pending)} origins")

    paths = {destination: [destination]}
    for origin in origins:
        if origin == destination:
            continue
        path = [origin]
        while path[-1] != destination:
            path.append(parent[path[-1]])
        paths[origin] = path
    for node in touched:
        distances[node] = float("inf")
    return paths, found_distance


def _site_by_zone(scenario: dict) -> dict[str, dict[str, dict]]:
    sites: dict[str, dict[str, dict]] = {}
    for zone in scenario["engine_input"]["zones"]:
        zone_id = zone["zone_id"]
        engine = zone["engine_input"]
        depots = scenario["depots_by_zone"][zone_id]
        rows = {
            depots["start"]["node_id"]: depots["start"],
            depots["end"]["node_id"]: depots["end"],
        }
        for candidate in engine["candidates"]:
            rows[candidate["candidate_id"]] = candidate
        sites[zone_id] = rows
    return sites


def build_route_legs(scenario: dict, context: dict) -> tuple[list[dict], float]:
    attachments = scenario["travel_model"]["attachments_by_zone"]
    sites = _site_by_zone(scenario)
    zone_engines = {
        zone["zone_id"]: zone["engine_input"]
        for zone in scenario["engine_input"]["zones"]
    }
    distances = array("d", [float("inf")]) * len(context["lats"])
    legs = []
    maximum_delta = 0.0

    for zone_id in sorted(zone_engines):
        engine = zone_engines[zone_id]
        attached = {
            row["node_id"]: row
            for row in attachments[zone_id]
        }
        site_ids = sorted(engine["distance_km"])
        origin_nodes = {int(attached[site_id]["osm_node_index"]) for site_id in site_ids}
        for destination_id in site_ids:
            destination_node = int(attached[destination_id]["osm_node_index"])
            paths, found = _paths_to_origins(
                context, destination_node, origin_nodes, distances
            )
            for origin_id in site_ids:
                if origin_id == destination_id:
                    continue
                origin_node = int(attached[origin_id]["osm_node_index"])
                graph_nodes = paths[origin_node]
                origin_site = sites[zone_id][origin_id]
                destination_site = sites[zone_id][destination_id]
                full_path = [
                    (float(origin_site["lon"]), float(origin_site["lat"])),
                    *[(context["lons"][node], context["lats"][node]) for node in graph_nodes],
                    (float(destination_site["lon"]), float(destination_site["lat"])),
                ]
                matrix_distance = float(engine["distance_km"][origin_id][destination_id])
                recovered_distance = (
                    found[origin_node]
                    + float(attached[origin_id]["connector_km"])
                    + float(attached[destination_id]["connector_km"])
                )
                delta = abs(matrix_distance - recovered_distance)
                maximum_delta = max(maximum_delta, delta)
                if delta > 0.002:
                    raise RuntimeError(
                        f"matrix/path mismatch {zone_id} {origin_id}->{destination_id}: "
                        f"{matrix_distance:.6f} vs {recovered_distance:.6f}"
                    )
                legs.append({
                    "zone_id": zone_id,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "matrix_km": round(matrix_distance, 3),
                    "network_node_count": len(graph_nodes),
                    "path": rounded(simplify_line(full_path, ROUTE_TOLERANCE)),
                    "node_sample": _sample_nodes(
                        graph_nodes,
                        context["lats"],
                        context["lons"],
                        MAX_NODE_SAMPLE_PER_LEG,
                    ),
                })
    return legs, maximum_delta


def zone_labels() -> list[dict]:
    with ACCESS_FILE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        grouped[service_zone(row["sigungu"])].append(
            (float(row["lon"]), float(row["lat"]))
        )
    return [
        {
            "zone_id": zone,
            "lon": round(sum(lon for lon, _ in points) / len(points), 6),
            "lat": round(sum(lat for _, lat in points) / len(points), 6),
        }
        for zone, points in sorted(grouped.items())
    ]


def build_payload() -> dict:
    if not PBF.exists() or not BOUNDARY_FILE.exists():
        raise RuntimeError("OSM PBF and SGIS boundary files are required")
    scenario = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    roadnet = json.loads((DATA_OUT / "roadnet_metadata.json").read_text(encoding="utf-8"))
    if scenario["travel_model"]["pbf_md5"] != roadnet["pbf_md5"]:
        raise RuntimeError("scenario and road-network PBF hashes do not match")

    boundaries, bounds = extract_boundaries()
    print(f"[map 1/3] 전북 행정경계 {len(boundaries)}개", flush=True)
    major_roads, major_way_count = extract_major_roads(bounds)
    print(f"[map 2/3] OSM 주요도로 way {major_way_count:,}개", flush=True)
    context = load_graph_context()
    route_legs, maximum_delta = build_route_legs(scenario, context)
    print(f"[map 3/3] 방향성 경로 구간 {len(route_legs):,}개", flush=True)

    return {
        "analysis_date": scenario["analysis_date"],
        "bounds": bounds,
        "boundaries": boundaries,
        "zone_labels": zone_labels(),
        "major_roads": major_roads,
        "route_legs": route_legs,
        "source": {
            "boundary": "data/raw/hjd2026.geojson · SGIS 2026 행정동 경계",
            "roads": "data/raw/south-korea-latest.osm.pbf · OpenStreetMap",
            "pbf_md5": roadnet["pbf_md5"],
            "oneway_respected": True,
            "full_graph_active_nodes": roadnet["active_nodes"],
            "major_road_way_count": major_way_count,
            "route_leg_count": len(route_legs),
            "maximum_matrix_path_delta_km": round(maximum_delta, 6),
            "node_display_contract": (
                "active-route OSM nodes sampled to at most 64 per directed leg"
            ),
        },
    }


def main() -> int:
    payload = build_payload()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "const JEONBUK_MAP=" + encoded + ";\n"
        "if(typeof window!==\"undefined\")window.JEONBUK_MAP=JEONBUK_MAP;\n"
        "if(typeof module!==\"undefined\")module.exports=JEONBUK_MAP;\n",
        encoding="utf-8",
    )
    print(f"→ {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
