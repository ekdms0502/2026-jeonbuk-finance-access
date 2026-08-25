"""Build the UI-neutral province-wide mobile-finance route scenario."""

from __future__ import annotations

import csv
import hashlib
import heapq
import json
import math
import sys
from array import array

from config import DATA_OUT, ROOT
from route_scenario import MAX_EXACT_CANDIDATES, configure_province, solve_province

CONFIG_FILE = ROOT / "config" / "jeonbuk_route_default.json"
OUTPUT_FILE = DATA_OUT / "jeonbuk_route_scenario.json"


def read_csv(path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    radians = math.radians
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(radians(lat1))
        * math.cos(radians(lat2))
        * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def service_zone(sigungu: str) -> str:
    return "전주시" if sigungu.startswith("전주시") else sigungu


def priority_tier(config: dict, road_km: float) -> str:
    for tier in config["priority_tiers"]:
        if road_km > float(tier["road_km_gt"]):
            return tier["tier_id"]
    raise RuntimeError(f"priority tier missing for road_km={road_km}")


def select_targets(
    config: dict,
    access_rows: list[dict],
    typology_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    typology = {row["code"]: row for row in typology_rows}
    threshold = float(config["target_selector"]["road_km_gt"])
    require_primary = bool(
        config["target_selector"].get("require_road_distance_primary", False)
    )
    targets = []
    excluded = []
    for row in access_rows:
        road_km = float(row["road_km"])
        if road_km <= threshold:
            continue
        if require_primary and row["road_distance_primary"] != "Y":
            excluded.append({
                "target_id": row["code"],
                "sigungu": row["sigungu"],
                "name": row["dong"],
                "road_km": road_km,
                "route_status": row["route_status"],
                "reason": "road_distance_not_primary",
            })
            continue
        type_row = typology[row["code"]]
        targets.append({
            "target_id": row["code"],
            "service_zone": service_zone(row["sigungu"]),
            "sigungu": row["sigungu"],
            "name": row["dong"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "road_km": road_km,
            "ratio_65plus": float(row["ratio_65plus"]),
            "cluster_label": type_row["cluster_label"],
            "rule_type": type_row["rule_type"],
            "road_distance_primary": row["road_distance_primary"],
            "priority_tier": priority_tier(config, road_km),
        })
    return (
        sorted(targets, key=lambda row: row["target_id"]),
        sorted(excluded, key=lambda row: row["target_id"]),
    )


def select_candidates(config: dict, targets: list[dict], venues: list[dict]) -> list[dict]:
    eligible = [row for row in venues if row["source_sigungu_match"] == "Y"]
    count = int(config["candidate_count_per_target"])
    if count <= 0:
        raise ValueError("candidate_count_per_target must be positive")
    candidates = []
    for target in targets:
        local = [
            row for row in eligible
            if row["coord_admin_code"] == target["target_id"]
        ]
        local.sort(key=lambda row: (
            haversine(
                target["lat"], target["lon"], float(row["lat"]), float(row["lon"])
            ),
            row["venue_id"],
        ))
        for rank, venue in enumerate(local[:count], 1):
            candidates.append({
                "candidate_id": venue["venue_id"],
                "service_zone": target["service_zone"],
                "name": venue["name"],
                "addr": venue["addr"],
                "lat": float(venue["lat"]),
                "lon": float(venue["lon"]),
                "serves_target_ids": [target["target_id"]],
                "selection_rank_for_target": rank,
                "selection_basis": (
                    "nearest_same_admin_boundary_audited_senior_center"
                ),
                "selection_distance_km": round(haversine(
                    target["lat"], target["lon"],
                    float(venue["lat"]), float(venue["lon"]),
                ), 6),
                "source_sigungu_match": venue["source_sigungu_match"],
                "geocode_method": venue["geocode_method"],
                "use_approval_status": venue["use_approval_status"],
                "service_minutes": int(config["service_minutes_default"]),
                "time_window_start": config["venue_time_window_default"]["start"],
                "time_window_end": config["venue_time_window_default"]["end"],
                "time_window_source": "scenario_default_not_source_data",
            })
    return sorted(candidates, key=lambda row: row["candidate_id"])


def outlet_zone(row: dict) -> str:
    return service_zone(row.get("coord_sigungu") or row["sigungu"])


def select_depot(
    config: dict,
    outlets: list[dict],
    zone: str,
    targets: list[dict],
    kind: str,
    default: dict | None = None,
) -> dict:
    override = config["depot"][f"{kind}_outlet_id_by_zone"].get(zone)
    if kind == "end" and not override and default is not None:
        return {**default, "selection_basis": "same_as_start_default"}
    local = [
        row for row in outlets
        if row["finance_open"] == "Y" and outlet_zone(row) == zone
    ]
    if override:
        local = [row for row in local if row["outlet_id"] == override]
        basis = "configured_outlet_override"
    else:
        preferred = set(config["depot"]["preferred_outlet_types"])
        preferred_rows = [row for row in local if row["type"] in preferred]
        if preferred_rows:
            local = preferred_rows
        basis = "nearest_preferred_open_outlet_to_zone_target_centroid"
    if not local:
        raise RuntimeError(f"eligible {kind} depot not found for {zone}")
    center_lat = sum(row["lat"] for row in targets) / len(targets)
    center_lon = sum(row["lon"] for row in targets) / len(targets)
    local.sort(key=lambda row: (
        haversine(center_lat, center_lon, float(row["lat"]), float(row["lon"])),
        row["outlet_id"],
    ))
    row = local[0]
    return {
        "node_id": row["outlet_id"],
        "name": row["name"],
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "source": "validated_financial_outlet",
        "selection_basis": basis,
        "confirmation_status": "unverified_as_operational_depot",
    }


def reverse_distance_to_origins(
    offsets: array,
    neighbors: array,
    weights: array,
    destination_node: int,
    destination_connector_km: float,
    origin_nodes: set[int],
) -> dict[int, float]:
    distances = array("d", [float("inf")]) * (len(offsets) - 1)
    distances[destination_node] = destination_connector_km
    heap = [(destination_connector_km, destination_node)]
    remaining = set(origin_nodes)
    found: dict[int, float] = {}
    while heap and remaining:
        distance, node = heapq.heappop(heap)
        if distance != distances[node]:
            continue
        if node in remaining:
            found[node] = distance
            remaining.remove(node)
        for position in range(offsets[node], offsets[node + 1]):
            next_node = neighbors[position]
            next_distance = distance + weights[position]
            if next_distance < distances[next_node]:
                distances[next_node] = next_distance
                heapq.heappush(heap, (next_distance, next_node))
    if remaining:
        raise RuntimeError(f"directed route missing for {len(remaining)} origin nodes")
    return found


def transpose_unweighted_csr(offsets: array, neighbors: array) -> tuple[array, array]:
    """Return the opposite directed adjacency without duplicating weights."""

    node_count = len(offsets) - 1
    degree = array("I", [0]) * node_count
    for destination in neighbors:
        degree[destination] += 1
    transposed_offsets = array("Q", [0])
    total = 0
    for value in degree:
        total += value
        transposed_offsets.append(total)
    transposed_neighbors = array("I", [0]) * total
    cursor = array("Q", transposed_offsets[:-1])
    for origin in range(node_count):
        for position in range(offsets[origin], offsets[origin + 1]):
            destination = neighbors[position]
            write_at = cursor[destination]
            transposed_neighbors[write_at] = origin
            cursor[destination] += 1
    return transposed_offsets, transposed_neighbors


def reachable_nodes(offsets: array, neighbors: array, start: int) -> bytearray:
    visited = bytearray(len(offsets) - 1)
    visited[start] = 1
    stack = array("I", [start])
    while stack:
        node = stack.pop()
        for position in range(offsets[node], offsets[node + 1]):
            next_node = neighbors[position]
            if visited[next_node]:
                continue
            visited[next_node] = 1
            stack.append(next_node)
    return visited


def load_graph_context() -> dict:
    from build_roadnet import MAX_SNAP_KM, PBF, build_graph, build_grid, nearby_nodes

    if not PBF.exists():
        raise RuntimeError(f"OSM PBF missing: {PBF}")
    _, lats, lons, active, offsets, neighbors, weights, _, _ = build_graph()
    forward_offsets, forward_neighbors = transpose_unweighted_csr(offsets, neighbors)
    return {
        "lats": lats,
        "lons": lons,
        "offsets": offsets,
        "neighbors": neighbors,
        "weights": weights,
        "forward_offsets": forward_offsets,
        "forward_neighbors": forward_neighbors,
        "grid": build_grid(lats, lons, active),
        "nearby_nodes": nearby_nodes,
        "max_snap_km": MAX_SNAP_KM,
    }


def build_zone_matrix(
    config: dict,
    context: dict,
    sites: list[dict],
    anchor_node_id: str,
) -> tuple[dict, dict, list[dict]]:
    anchor_site = next(site for site in sites if site["node_id"] == anchor_node_id)
    anchor_nearby = context["nearby_nodes"](
        context["grid"], context["lats"], context["lons"],
        anchor_site["lat"], anchor_site["lon"], slack_km=0.0,
    )
    if not anchor_nearby:
        raise RuntimeError(f"route anchor snap failed: {anchor_node_id}")
    anchor_nearby.sort(key=lambda row: (row[1], row[0]))
    anchor_node = anchor_nearby[0][0]
    # The stored graph is reversed.  Mutual reachability with the anchor puts
    # every selected attachment in the same directed strongly connected set.
    can_reach_anchor = reachable_nodes(
        context["offsets"], context["neighbors"], anchor_node
    )
    reachable_from_anchor = reachable_nodes(
        context["forward_offsets"], context["forward_neighbors"], anchor_node
    )

    attachments = {}
    attachment_rows = []
    for site in sites:
        nearby = context["nearby_nodes"](
            context["grid"], context["lats"], context["lons"],
            site["lat"], site["lon"],
            max_km=context["max_snap_km"],
            slack_km=context["max_snap_km"],
        )
        if not nearby:
            raise RuntimeError(f"route node snap failed: {site['node_id']}")
        nearby.sort(key=lambda row: (row[1], row[0]))
        mutually_reachable = [
            (node, connector) for node, connector in nearby
            if can_reach_anchor[node] and reachable_from_anchor[node]
        ]
        if not mutually_reachable:
            raise RuntimeError(
                f"no mutually reachable road node within "
                f"{context['max_snap_km']}km: {site['node_id']}"
            )
        node, connector = mutually_reachable[0]
        strategy = (
            "exact_nearest_node"
            if (node, connector) == nearby[0]
            else "nearest_mutually_reachable_node_fallback"
        )
        attachments[site["node_id"]] = (node, connector)
        attachment_rows.append({
            "node_id": site["node_id"],
            "osm_node_index": node,
            "connector_km": round(connector, 6),
            "snap_strategy": strategy,
        })

    distance_matrix = {site["node_id"]: {} for site in sites}
    origin_nodes = {node for node, _ in attachments.values()}
    for destination in sites:
        destination_node, destination_connector = attachments[destination["node_id"]]
        network_to_destination = reverse_distance_to_origins(
            context["offsets"], context["neighbors"], context["weights"],
            destination_node, destination_connector, origin_nodes,
        )
        for origin in sites:
            if origin["node_id"] == destination["node_id"]:
                distance = 0.0
            else:
                origin_node, origin_connector = attachments[origin["node_id"]]
                distance = origin_connector + network_to_destination[origin_node]
            distance_matrix[origin["node_id"]][destination["node_id"]] = round(distance, 6)

    speed = float(config["travel_time_assumption"]["uniform_speed_kmh"])
    travel_matrix = {
        origin: {
            destination: round(distance / speed * 60, 6)
            for destination, distance in row.items()
        }
        for origin, row in distance_matrix.items()
    }
    return distance_matrix, travel_matrix, attachment_rows


def input_paths() -> dict[str, object]:
    return {
        "access_road_sha256": DATA_OUT / "access_road.csv",
        "access_typology_sha256": DATA_OUT / "access_typology.csv",
        "venues_jeonbuk_sha256": DATA_OUT / "venues_jeonbuk.csv",
        "outlets_validated_sha256": DATA_OUT / "outlets_validated.csv",
        "scenario_config_sha256": CONFIG_FILE,
    }


def current_input_hashes() -> dict[str, str]:
    return {name: sha256(path) for name, path in input_paths().items()}


def matrix_contract(config: dict) -> dict:
    return {
        "target_selector": config["target_selector"],
        "priority_tiers": config["priority_tiers"],
        "candidate_count_per_target": config["candidate_count_per_target"],
        "depot": config["depot"],
    }


def sensitivity_summary(config: dict, engine_input: dict) -> list[dict]:
    summaries = []
    target_count = sum(
        len(zone["engine_input"]["targets"])
        for zone in engine_input["zones"]
    )
    for preset in config["sensitivity_presets"]:
        parameters = {
            key: preset[key]
            for key in (
                "vehicle_count",
                "operating_days_per_cycle",
                "operating_start",
                "operating_end",
                "service_minutes",
                "max_stops_per_route",
            )
        }
        scenario_input = configure_province(engine_input, parameters)
        result = solve_province(scenario_input)
        optimized = result["optimized"]
        summaries.append({
            "preset_id": preset["preset_id"],
            "label": preset["label"],
            "parameters": parameters,
            "minimum_route_days_per_active_zone": scenario_input[
                "minimum_route_days_per_active_zone"
            ],
            "all_zones_allocated": all(
                row["allocated_route_days"] > 0
                for row in result["zone_allocations"]
            ),
            "result": {
                "coverage_by_tier": optimized["coverage_by_tier"],
                "covered_target_count": optimized["covered_target_count"],
                "target_count": target_count,
                "route_days_used": optimized["route_days_used"],
                "unvisited_target_count": len(optimized["unvisited_targets"]),
                "totals": optimized["totals"],
                "zone_allocations": result["zone_allocations"],
            },
        })
    return summaries


def attach_sensitivity(output: dict, config: dict) -> None:
    output["input_controls"] = config["input_controls"]
    output["sensitivity_presets"] = sensitivity_summary(
        config, output["engine_input"]
    )


def attach_measurement_contract(output: dict) -> None:
    candidates = [
        candidate
        for zone in output["engine_input"]["zones"]
        for candidate in zone["engine_input"]["candidates"]
    ]
    output["measurement_contract"] = {
        "covered_target_count_meaning": (
            "visited administrative representative-point target count"
        ),
        "resident_coverage_available": False,
        "population_exposure_valid": False,
        "candidate_location_optimization_performed": False,
        "candidate_count_per_target": 1,
        "every_candidate_serves_exactly_one_target": all(
            len(candidate["serves_target_ids"]) == 1 for candidate in candidates
        ),
        "required_upgrade_for_resident_coverage": (
            "resident-level or 100m/500m age-grid origins with the same road-access model"
        ),
    }
    output["selection_contract"]["candidate_location_optimization_performed"] = False
    output["selection_contract"]["candidate_role"] = (
        "one venue proxy for one administrative target"
    )


def apply_reusable_config(output: dict, config: dict) -> None:
    if output.get("matrix_contract") != matrix_contract(config):
        raise RuntimeError(
            "대상·우선순위·후보·차고지가 바뀌었습니다. --reuse-matrix 없이 실행하세요."
        )
    current_hashes = current_input_hashes()
    for name, observed in current_hashes.items():
        if name in {"scenario_config_sha256", "access_typology_sha256"}:
            continue
        if output["input_hashes"].get(name) != observed:
            raise RuntimeError(f"input changed ({name}); rebuild OSM matrices")

    typology = {
        row["code"]: row for row in read_csv(DATA_OUT / "access_typology.csv")
    }
    for zone in output["engine_input"]["zones"]:
        for target in zone["engine_input"]["targets"]:
            type_row = typology[target["target_id"]]
            target["cluster_label"] = type_row["cluster_label"]
            target["rule_type"] = type_row["rule_type"]

    engine = output["engine_input"]
    engine.update({
        "vehicle_count": int(config["vehicle_count"]),
        "operating_days_per_cycle": int(config["operating_days_per_cycle"]),
        "minimum_route_days_per_active_zone": int(
            config["minimum_route_days_per_active_zone"]
        ),
        "service_cycle_days": int(config["service_cycle_days"]),
    })
    speed = float(config["travel_time_assumption"]["uniform_speed_kmh"])
    if speed <= 0:
        raise ValueError("uniform_speed_kmh must be positive")
    for zone in engine["zones"]:
        zone_input = zone["engine_input"]
        zone_input.update({
            "max_stops_per_vehicle": min(
                int(config["max_stops_per_route"]), len(zone_input["candidates"])
            ),
            "service_cycle_days": int(config["service_cycle_days"]),
            "operating_start": config["operating_start"],
            "operating_end": config["operating_end"],
        })
        for candidate in zone_input["candidates"]:
            candidate["service_minutes"] = int(config["service_minutes_default"])
            candidate["time_window_start"] = config["venue_time_window_default"]["start"]
            candidate["time_window_end"] = config["venue_time_window_default"]["end"]
        zone_input["travel_minutes"] = {
            origin: {
                destination: round(float(distance) / speed * 60, 6)
                for destination, distance in row.items()
            }
            for origin, row in zone_input["distance_km"].items()
        }
    output["scenario_id"] = config["scenario_id"]
    output["analysis_date"] = config["analysis_date"]
    output["travel_model"]["uniform_speed_kmh"] = speed
    output["input_hashes"]["scenario_config_sha256"] = current_hashes[
        "scenario_config_sha256"
    ]
    output["input_hashes"]["access_typology_sha256"] = current_hashes[
        "access_typology_sha256"
    ]
    output["results"] = solve_province(engine)
    attach_sensitivity(output, config)
    attach_measurement_contract(output)


def main() -> int:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if "--reuse-matrix" in sys.argv:
        output = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        apply_reusable_config(output, config)
        OUTPUT_FILE.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        optimized = output["results"]["optimized"]
        print(
            f"저장 행렬 재계산: {optimized['covered_target_count']}개 대표점 대상 방문·"
            f"{optimized['route_days_used']}개 경로일"
        )
        return 0

    access_path = DATA_OUT / "access_road.csv"
    typology_path = DATA_OUT / "access_typology.csv"
    venue_path = DATA_OUT / "venues_jeonbuk.csv"
    outlet_path = DATA_OUT / "outlets_validated.csv"
    access_rows = read_csv(access_path)
    targets, excluded_targets = select_targets(
        config, access_rows, read_csv(typology_path)
    )
    candidates = select_candidates(config, targets, read_csv(venue_path))
    outlets = read_csv(outlet_path)
    zones = sorted({row["service_zone"] for row in targets})

    zone_parts = []
    depots = {}
    for zone in zones:
        zone_targets = [row for row in targets if row["service_zone"] == zone]
        zone_candidates = [row for row in candidates if row["service_zone"] == zone]
        if not zone_candidates:
            raise RuntimeError(f"no eligible route candidate in service zone: {zone}")
        if len(zone_candidates) > MAX_EXACT_CANDIDATES:
            raise RuntimeError(
                f"{zone} candidates {len(zone_candidates)} exceed exact limit "
                f"{MAX_EXACT_CANDIDATES}; lower candidate_count_per_target"
            )
        start = select_depot(config, outlets, zone, zone_targets, "start")
        end = select_depot(config, outlets, zone, zone_targets, "end", start)
        depots[zone] = {"start": start, "end": end}
        zone_parts.append((zone, zone_targets, zone_candidates, start, end))

    context = load_graph_context()
    engine_zones = []
    attachments_by_zone = {}
    for zone, zone_targets, zone_candidates, start, end in zone_parts:
        site_by_id = {start["node_id"]: start, end["node_id"]: end}
        for candidate in zone_candidates:
            site_by_id[candidate["candidate_id"]] = {
                "node_id": candidate["candidate_id"],
                "name": candidate["name"],
                "lat": candidate["lat"],
                "lon": candidate["lon"],
                "source": "official_senior_center_candidate",
            }
        sites = [site_by_id[node_id] for node_id in sorted(site_by_id)]
        distance_matrix, travel_matrix, attachments = build_zone_matrix(
            config, context, sites, start["node_id"]
        )
        attachments_by_zone[zone] = attachments
        engine_zones.append({
            "zone_id": zone,
            "engine_input": {
                "vehicle_count": 1,
                "max_stops_per_vehicle": min(
                    int(config["max_stops_per_route"]), len(zone_candidates)
                ),
                "service_cycle_days": int(config["service_cycle_days"]),
                "operating_start": config["operating_start"],
                "operating_end": config["operating_end"],
                "start_node_id": start["node_id"],
                "end_node_id": end["node_id"],
                "priority_tiers": [
                    {"tier_id": row["tier_id"], "description": row["description"]}
                    for row in config["priority_tiers"]
                ],
                "targets": zone_targets,
                "candidates": zone_candidates,
                "distance_km": distance_matrix,
                "travel_minutes": travel_matrix,
            },
        })
        print(
            f"  {zone}: 대상 {len(zone_targets)}·후보 {len(zone_candidates)}·"
            f"경로노드 {len(sites)}",
            flush=True,
        )

    engine_input = {
        "vehicle_count": int(config["vehicle_count"]),
        "operating_days_per_cycle": int(config["operating_days_per_cycle"]),
        "minimum_route_days_per_active_zone": int(
            config["minimum_route_days_per_active_zone"]
        ),
        "service_cycle_days": int(config["service_cycle_days"]),
        "priority_tiers": [
            {"tier_id": row["tier_id"], "description": row["description"]}
            for row in config["priority_tiers"]
        ],
        "zones": engine_zones,
    }
    results = solve_province(engine_input)
    roadnet_metadata = json.loads(
        (DATA_OUT / "roadnet_metadata.json").read_text(encoding="utf-8")
    )
    threshold_count = sum(
        float(row["road_km"]) > float(config["target_selector"]["road_km_gt"])
        for row in access_rows
    )
    output = {
        "scenario_id": config["scenario_id"],
        "analysis_date": config["analysis_date"],
        "status": "demonstration_not_operational",
        "operational_ready": False,
        "input_hashes": current_input_hashes(),
        "scope": {
            "analysis_admin_count": len(access_rows),
            "analysis_service_zone_count": len({service_zone(row["sigungu"]) for row in access_rows}),
            "threshold_target_count": threshold_count,
            "route_eligible_target_count": len(targets),
            "route_quality_deferred_count": len(excluded_targets),
            "candidate_count": len(candidates),
        },
        "travel_model": {
            "distance": "directed_osm_shortest_distance_with_endpoint_connectors_by_zone",
            "oneway_respected": True,
            "pbf_md5": roadnet_metadata["pbf_md5"],
            "time": "distance_divided_by_uniform_speed_free_flow_assumption",
            "uniform_speed_kmh": config["travel_time_assumption"]["uniform_speed_kmh"],
            "actual_traffic_time": False,
            "interzone_repositioning_modeled": False,
            "attachments_by_zone": attachments_by_zone,
        },
        "selection_contract": {
            "service_zones": "14 Jeonbuk municipalities; two Jeonju districts combined",
            "target_selector": config["target_selector"],
            "candidate_selector": (
                "nearest source-city-matched boundary-audited senior center in each target admin"
            ),
            "candidate_location_distance": "haversine_to_admin_representative_point",
            "candidate_location_optimization_performed": False,
            "candidate_role": "one venue proxy for one administrative target",
        },
        "matrix_contract": matrix_contract(config),
        "excluded_targets": excluded_targets,
        "depots_by_zone": depots,
        "engine_input": engine_input,
        "results": results,
        "assumption_flags": [
            "all venue use approvals are unverified",
            "all venue time windows use scenario defaults",
            "all zone depots are algorithmic candidates, not confirmed operations bases",
            "vehicle repositioning between service zones is not modeled",
            "weekly service cycle is a scenario assumption",
            "travel time is a uniform-speed free-flow estimate, not observed traffic",
            "targets are administrative representative-point proxies, not resident locations",
            "non-primary road-distance targets are deferred rather than ranked",
        ],
    }
    attach_sensitivity(output, config)
    attach_measurement_contract(output)
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    optimized = results["optimized"]
    print(
        f"전북 순회 시나리오: 243개 분석·14개 시군·"
        f"{len(targets)}개 경로대상·{len(excluded_targets)}개 품질유보"
    )
    print(
        f"  차량 {config['vehicle_count']}대·경로일 {optimized['route_days_used']}·"
        f"대표점 대상 방문 {optimized['covered_target_count']}/{len(targets)}·"
        f"이동 {optimized['totals']['travel_km']:.1f}km"
    )
    print(f"→ {OUTPUT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
