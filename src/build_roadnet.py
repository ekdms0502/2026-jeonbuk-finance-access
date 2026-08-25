"""Build an exact, directed OSM road-distance proxy for 243 admin areas.

Key correctness properties:
  * bbox is derived from all Jeonbuk SGIS geometries, including islands;
  * no connected component is discarded;
  * OSM one-way direction is respected;
  * graph-node snapping is an exact grid search within the accepted radius;
  * one reverse multi-source Dijkstra considers every analysis-eligible outlet;
  * endpoint snap legs are included in the reported road proxy.

The result still starts at one interior representative point per administrative
dong, so it must not be interpreted as a resident-level exposure distance.
"""

from __future__ import annotations

import csv
import gc
import hashlib
import heapq
import json
import math
import sys
from array import array
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import osmium

from config import ROOT, DATA_RAW, DATA_OUT
from geo_utils import combined_bbox

PBF = DATA_RAW / "south-korea-latest.osm.pbf"
GEOJSON = DATA_RAW / "hjd2026.geojson"
ACCESS = DATA_OUT / "access_jeonbuk.csv"
OUTLETS = DATA_OUT / "outlets_validated.csv"
MAX_SNAP_KM = 2.0
GRID_DEGREES = 0.01
DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "service", "road",
}
BLOCKED_ACCESS = {"no", "private"}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p = math.radians
    dlat, dlon = p(lat2 - lat1), p(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def jeonbuk_bbox() -> tuple[float, float, float, float]:
    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))
    geometries = [f["geometry"] for f in geo["features"] if f["properties"].get("sido") == "52"]
    # A 0.25-degree buffer lets border routes leave Jeonbuk and re-enter.  The
    # western expansion is mostly sea but is necessary to retain island roads.
    return combined_bbox(geometries, margin_degrees=0.25)


def _allowed_way(tags) -> bool:
    if tags.get("highway") not in DRIVABLE:
        return False
    return not any(tags.get(key) in BLOCKED_ACCESS for key in ("access", "vehicle", "motor_vehicle"))


def _directions(tags) -> tuple[bool, bool]:
    """Return (original-node-order allowed, reverse allowed)."""
    value = tags.get("oneway:motor_vehicle") or tags.get("oneway") or ""
    value = value.lower()
    if value in {"yes", "true", "1"}:
        return True, False
    if value in {"-1", "reverse"}:
        return False, True
    if value in {"no", "false", "0"}:
        return True, True
    if tags.get("junction") == "roundabout" or tags.get("highway") in {"motorway", "motorway_link"}:
        return True, False
    return True, True


class RoadNodeIdHandler(osmium.SimpleHandler):
    """First PBF pass: collect IDs referenced by drivable ways."""

    def __init__(self):
        super().__init__()
        self.ids: set[int] = set()
        self.way_count = 0

    def way(self, way):
        if not _allowed_way(way.tags):
            return
        self.way_count += 1
        self.ids.update(node.ref for node in way.nodes)


class CoordinateHandler(osmium.SimpleHandler):
    """Second pass: retain referenced nodes within the full Jeonbuk bbox."""

    def __init__(self, needed: set[int], bbox: tuple[float, float, float, float]):
        super().__init__()
        self.needed = needed
        self.bbox = bbox
        self.node_ids = array("q")
        self.lats = array("d")
        self.lons = array("d")

    def node(self, node):
        if node.id not in self.needed or not node.location.valid():
            return
        lat, lon = node.location.lat, node.location.lon
        min_lat, max_lat, min_lon, max_lon = self.bbox
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            self.node_ids.append(node.id)
            self.lats.append(lat)
            self.lons.append(lon)


class ReverseEdgeHandler(osmium.SimpleHandler):
    """Third pass: create directed edges already reversed for outlet search."""

    def __init__(self, node_index: dict[int, int], lats: array, lons: array):
        super().__init__()
        self.node_index = node_index
        self.lats = lats
        self.lons = lons
        self.src = array("I")
        self.dst = array("I")
        self.weights = array("f")
        self.degree = array("I", [0]) * len(lats)
        self.active = bytearray(len(lats))
        self.local_way_count = 0

    def _add(self, src: int, dst: int, weight: float) -> None:
        self.src.append(src)
        self.dst.append(dst)
        self.weights.append(weight)
        self.degree[src] += 1
        self.active[src] = 1
        self.active[dst] = 1

    def way(self, way):
        if not _allowed_way(way.tags):
            return
        forward, backward = _directions(way.tags)
        refs = [node.ref for node in way.nodes]
        touched = False
        for left_id, right_id in zip(refs, refs[1:]):
            left = self.node_index.get(left_id)
            right = self.node_index.get(right_id)
            if left is None or right is None:
                continue
            weight = haversine(self.lats[left], self.lons[left], self.lats[right], self.lons[right])
            if weight <= 0:
                continue
            # Original left -> right becomes right -> left in the reversed graph.
            if forward:
                self._add(right, left, weight)
            if backward:
                self._add(left, right, weight)
            touched = True
        if touched:
            self.local_way_count += 1


def build_csr(handler: ReverseEdgeHandler) -> tuple[array, array, array, bytearray]:
    """Convert edge arrays to compact CSR adjacency."""
    offsets = array("Q", [0])
    total = 0
    for degree in handler.degree:
        total += degree
        offsets.append(total)
    neighbors = array("I", [0]) * total
    weights = array("f", [0.0]) * total
    cursor = array("Q", offsets[:-1])
    for src, dst, weight in zip(handler.src, handler.dst, handler.weights):
        pos = cursor[src]
        neighbors[pos] = dst
        weights[pos] = weight
        cursor[src] += 1
    active = handler.active
    return offsets, neighbors, weights, active


def build_graph():
    bbox = jeonbuk_bbox()
    print(f"[1/6] 차량 도로 노드 ID 스캔 — {PBF.name}")
    ids = RoadNodeIdHandler()
    ids.apply_file(str(PBF), locations=False)
    print(f"      전국 차량 way {ids.way_count:,}개 · 참조 노드 {len(ids.ids):,}개")

    print(f"[2/6] 전북 전 섬역 포함 bbox 노드 추출: {bbox}")
    coords = CoordinateHandler(ids.ids, bbox)
    coords.apply_file(str(PBF), locations=False)
    print(f"      bbox 차량도로 참조 노드 {len(coords.node_ids):,}개")
    del ids
    gc.collect()

    node_index = {node_id: i for i, node_id in enumerate(coords.node_ids)}
    print("[3/6] 일방통행을 반영한 역방향 엣지 구성")
    edges = ReverseEdgeHandler(node_index, coords.lats, coords.lons)
    edges.apply_file(str(PBF), locations=False)
    edge_count = len(edges.src)
    print(f"      bbox way {edges.local_way_count:,}개 · 방향 엣지 {edge_count:,}개")
    del node_index, coords.node_ids
    gc.collect()

    print("[4/6] 압축 인접행렬(CSR) 변환")
    offsets, neighbors, weights, active = build_csr(edges)
    lats, lons = edges.lats, edges.lons
    active_count = sum(active)
    del edges
    gc.collect()
    print(f"      활성 노드 {active_count:,}개 · 연결요소 삭제 없음")
    return bbox, lats, lons, active, offsets, neighbors, weights, edge_count, active_count


def build_grid(lats: array, lons: array, active: bytearray) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, flag in enumerate(active):
        if flag:
            grid[(math.floor(lats[idx] / GRID_DEGREES),
                  math.floor(lons[idx] / GRID_DEGREES))].append(idx)
    return dict(grid)


def _ring_cells(center_y: int, center_x: int, radius: int):
    if radius == 0:
        yield center_y, center_x
        return
    for x in range(center_x - radius, center_x + radius + 1):
        yield center_y - radius, x
        yield center_y + radius, x
    for y in range(center_y - radius + 1, center_y + radius):
        yield y, center_x - radius
        yield y, center_x + radius


def nearby_nodes(grid: dict[tuple[int, int], list[int]], lats: array, lons: array,
                 lat: float, lon: float, max_km: float = MAX_SNAP_KM,
                 slack_km: float = 0.0) -> list[tuple[int, float]]:
    """Return every node within min(nearest+slack, max_km), exactly."""
    center_y = math.floor(lat / GRID_DEGREES)
    center_x = math.floor(lon / GRID_DEGREES)
    best_dist = float("inf")
    candidates: list[tuple[int, float]] = []
    radius = 0
    while radius <= 200:
        for cell in _ring_cells(center_y, center_x, radius):
            for node in grid.get(cell, ()):
                dist = haversine(lat, lon, lats[node], lons[node])
                if dist < best_dist:
                    best_dist = dist
                candidates.append((node, dist))

        south = lat - (center_y - radius) * GRID_DEGREES
        north = (center_y + radius + 1) * GRID_DEGREES - lat
        west = lon - (center_x - radius) * GRID_DEGREES
        east = (center_x + radius + 1) * GRID_DEGREES - lon
        # 80 km/degree is a conservative lower bound in Korea for both axes.
        outside_lower_bound = min(south, north, west, east) * 80.0
        threshold = min(max_km, best_dist + slack_km) if math.isfinite(best_dist) else max_km
        if outside_lower_bound > threshold:
            if best_dist > max_km:
                return []
            return sorted((node, dist) for node, dist in candidates if dist <= threshold + 1e-12)
        radius += 1
    raise RuntimeError("nearest-node grid search did not converge")


def multi_source_to_targets(offsets: array, neighbors: array, weights: array,
                            attachments: list[tuple[int, float, int]]):
    node_count = len(offsets) - 1
    distances = array("d", [float("inf")]) * node_count
    origins = array("i", [-1]) * node_count
    seed_legs = array("f", [float("inf")]) * node_count
    heap: list[tuple[float, int, int]] = []
    for node, snap_km, outlet_idx in attachments:
        if snap_km < distances[node]:
            distances[node] = snap_km
            origins[node] = outlet_idx
            seed_legs[node] = snap_km
            heapq.heappush(heap, (snap_km, node, outlet_idx))

    pops = 0
    while heap:
        dist, node, origin = heapq.heappop(heap)
        if dist != distances[node] or origin != origins[node]:
            continue
        pops += 1
        start, end = offsets[node], offsets[node + 1]
        for pos in range(start, end):
            nxt = neighbors[pos]
            new_dist = dist + weights[pos]
            if new_dist < distances[nxt]:
                distances[nxt] = new_dist
                origins[nxt] = origin
                seed_legs[nxt] = seed_legs[node]
                heapq.heappush(heap, (new_dist, nxt, origin))
    return distances, origins, seed_legs, pops


def md5(path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not PBF.exists():
        print(f"PBF 없음: {PBF}")
        return 1

    (bbox, lats, lons, active, offsets, neighbors, weights,
     edge_count, active_count) = build_graph()
    print("[5/6] 도로 노드 정밀 스냅")
    grid = build_grid(lats, lons, active)
    del active
    gc.collect()

    access = list(csv.DictReader(ACCESS.read_text(encoding="utf-8-sig").splitlines()))
    outlets = [
        row for row in csv.DictReader(OUTLETS.read_text(encoding="utf-8-sig").splitlines())
        if row["finance_open"] == "Y"
    ]
    for row in outlets:
        row["lat"], row["lon"] = float(row["lat"]), float(row["lon"])

    outlet_attachments: list[tuple[int, float, int]] = []
    snapped_outlet_ids: set[str] = set()
    outlet_snap_failures: list[dict] = []
    for outlet_idx, row in enumerate(outlets):
        attachments = nearby_nodes(grid, lats, lons, row["lat"], row["lon"], slack_km=0.0)
        if not attachments:
            outlet_snap_failures.append(row)
        else:
            snapped_outlet_ids.add(row["outlet_id"])
            node, dist = attachments[0]
            outlet_attachments.append((node, dist, outlet_idx))
    print(f"      분석가용 접점 {len(snapped_outlet_ids)}/{len(outlets)} 스냅 "
          f"(도로 연결 {len(outlet_attachments):,}개)")

    admin_candidates: list[list[tuple[int, float]]] = []
    for row in access:
        admin_candidates.append(nearby_nodes(
            grid, lats, lons, float(row["lat"]), float(row["lon"]), slack_km=0.0
        ))
    print(f"      행정동 대표점 {sum(bool(s) for s in admin_candidates)}/{len(access)} 스냅")

    print("[6/6] 전체 접점 동시 최단경로 (후보수·cutoff 제한 없음)")
    distances, origins, seed_legs, heap_pops = multi_source_to_targets(
        offsets, neighbors, weights, outlet_attachments
    )

    out_rows = []
    for row, candidates in zip(access, admin_candidates):
        extra = {
            "road_km": "", "network_km": "", "admin_snap_km": "", "outlet_snap_km": "",
            "road_outlet_id": "", "road_nearest_name": "", "road_nearest_type": "",
            "route_straight_km": "", "detour": "", "route_status": "",
            "routing_method": "directed_all_outlet_reverse_multisource_dijkstra",
            "oneway_respected": "Y", "max_snap_km": MAX_SNAP_KM,
            "admin_snap_strategy": "", "route_quality": "", "road_distance_primary": "N",
        }
        if not candidates:
            extra["route_status"] = "admin_snap_failed"
        else:
            node, connector = candidates[0]
            if origins[node] >= 0:
                chosen = (node, connector)
                extra["admin_snap_strategy"] = "exact_nearest_node"
                extra["route_quality"] = "standard_proxy"
            else:
                # Rare directed dead-end: use the geographically nearest node
                # that can reach an eligible outlet.  Do not optimize across
                # farther nodes, which would create an artificial shortcut.
                expanded = nearby_nodes(
                    grid, lats, lons, float(row["lat"]), float(row["lon"]), slack_km=MAX_SNAP_KM
                )
                reachable = [(candidate_node, candidate_dist) for candidate_node, candidate_dist in expanded
                             if origins[candidate_node] >= 0]
                chosen = reachable[0] if reachable else None
                extra["admin_snap_strategy"] = "nearest_directed_reachable_node_fallback"
                extra["route_quality"] = "low_large_connector_fallback"
            if chosen is None:
                extra["route_status"] = "no_directed_path_to_eligible_outlet"
                out_rows.append({**row, **extra})
                continue
            admin_node, admin_connector = chosen
            road_km = admin_connector + distances[admin_node]
            origin = origins[admin_node]
            outlet = outlets[origin]
            outlet_snap = float(seed_legs[admin_node])
            network_km = max(0.0, distances[admin_node] - outlet_snap)
            direct = haversine(float(row["lat"]), float(row["lon"]), outlet["lat"], outlet["lon"])
            extra.update({
                "road_km": round(road_km, 3), "network_km": round(network_km, 3),
                "admin_snap_km": round(admin_connector, 3), "outlet_snap_km": round(outlet_snap, 3),
                "road_outlet_id": outlet["outlet_id"], "road_nearest_name": outlet["name"],
                "road_nearest_type": outlet["type"], "route_straight_km": round(direct, 3),
                "detour": round(road_km / direct, 3) if direct > 0 else "",
                "route_status": "ok" if extra["admin_snap_strategy"] == "exact_nearest_node"
                else "fallback_nearest_reachable",
                "road_distance_primary": "Y" if extra["admin_snap_strategy"] == "exact_nearest_node" else "N",
            })
        out_rows.append({**row, **extra})

    out = DATA_OUT / "access_road.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(out_rows[0].keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(out_rows)

    routed = [row for row in out_rows if row["road_km"] != ""]
    primary = [row for row in routed if row["road_distance_primary"] == "Y"]
    fallback = [row for row in routed if row["route_status"] == "fallback_nearest_reachable"]
    detours = sorted(float(row["detour"]) for row in primary if row["detour"] != "")
    metadata = {
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "pbf": str(PBF.relative_to(ROOT)),
        "pbf_md5": md5(PBF),
        "bbox_min_lat_max_lat_min_lon_max_lon": bbox,
        "active_nodes": active_count,
        "directed_reverse_edges": edge_count,
        "components_removed": 0,
        "drivable_highways": sorted(DRIVABLE),
        "oneway_respected": True,
        "blocked_access_values": sorted(BLOCKED_ACCESS),
        "max_snap_km": MAX_SNAP_KM,
        "eligible_outlets": len(outlets),
        "snapped_outlets": len(snapped_outlet_ids),
        "outlet_road_attachments": len(outlet_attachments),
        "outlet_snap_failures": [row["outlet_id"] for row in outlet_snap_failures],
        "admin_points": len(access),
        "snapped_admin_points": sum(bool(s) for s in admin_candidates),
        "routed_admin_points": len(routed),
        "primary_admin_points": len(primary),
        "fallback_admin_points": len(fallback),
        "unrouted_admin_points": len(access) - len(routed),
        "dijkstra_heap_pops": heap_pops,
        "candidate_limit": None,
        "cutoff_km": None,
        "distance_definition": "admin snap leg + directed OSM network + outlet snap leg",
        "population_exposure_valid": False,
    }
    (DATA_OUT / "roadnet_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = ROOT / "reports" / "quality_report.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    section_marker = "\n## 6. 도로거리 프록시"
    section_start = existing.find(section_marker)
    report_suffix = ""
    if section_start >= 0:
        next_section = existing.find("\n## ", section_start + len(section_marker))
        if next_section >= 0:
            report_suffix = existing[next_section:]
        existing = existing[:section_start].rstrip()
    road_lines = [
        "", "## 6. 도로거리 프록시", "",
        f"- OSM PBF MD5: `{metadata['pbf_md5']}`.",
        f"- 전북 전 섬역+경계 0.25도 완충 bbox, 활성 노드 {active_count:,}개, 방향 엣지 {edge_count:,}개.",
        "- OSM `oneway`를 반영하고 연결요소를 삭제하지 않았다.",
        f"- 분석가용 접점 {len(snapped_outlet_ids)}/{len(outlets)}, 행정동 {len(routed)}/{len(access)}에 수치가 있다.",
        f"- 표준 노드 스냅 {len(primary)}개, 대형 연결구간 폴백 {len(fallback)}개.",
        "- 접점 후보 수 제한과 다익스트라 cutoff는 사용하지 않았다.",
        "- `road_km = admin_snap_km + network_km + outlet_snap_km`.",
    ]
    if detours:
        road_lines.append(f"- 표준 {len(primary)}개의 우회계수 중앙값 {detours[len(detours)//2]:.3f}, 최솟값 {detours[0]:.3f}.")
    road_lines += [
        f"- 전체 대표점 프록시의 3km 초과 {sum(float(r['road_km']) > 3 for r in routed)}개, 5km 초과 {sum(float(r['road_km']) > 5 for r in routed)}개.",
        "- **위 임계치에 행정동 전체 인구를 합산하면 안 된다.**", "",
    ]
    if fallback:
        road_lines += [
            "### 대형 연결구간 폴백", "",
            "가장 가까운 OSM 노드가 일방통행·분리도로망에서 접점까지 도달할 수 없어, 2km 안의 가장 가까운 도달 가능 노드를 사용했다. `road_distance_primary=N`으로 필터할 수 있다.",
            "", "| 행정동 | 연결구간(km) | 도로거리(km) |", "|---|---:|---:|",
        ]
        for row in fallback:
            road_lines.append(f"| {row['sigungu']} {row['dong']} | {row['admin_snap_km']} | {row['road_km']} |")
    report.write_text(
        existing + "\n" + "\n".join(road_lines) + "\n" + report_suffix.lstrip("\n"),
        encoding="utf-8",
    )

    print(f"\n도로거리 {len(routed)}/{len(out_rows)} 산출 → {out.relative_to(ROOT)}")
    print(f"  표준 {len(primary)}개 · 대형 연결구간 폴백 {len(fallback)}개")
    if detours:
        print(f"  우회계수 중앙값 {detours[len(detours)//2]:.3f} · 최솟값 {detours[0]:.3f}")
    print(f"  3km 초과 대표점 {sum(float(r['road_km']) > 3 for r in routed)}개 (인구 합산 금지)")
    print(f"  5km 초과 대표점 {sum(float(r['road_km']) > 5 for r in routed)}개 (인구 합산 금지)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
