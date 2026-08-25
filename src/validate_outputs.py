"""Offline integrity checks for the competition-facing processed datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter

from config import DATA_RAW, DATA_OUT, ROOT
from geo_utils import point_in_geometry
from route_scenario import solve_province

EXPECTED_TYPES = {"우체국": 242, "은행": 175, "신협": 128, "새마을금고": 136}
EXPECTED_P65 = 470_160
EXPECTED_PBF_MD5 = "9269d6a6df9c7053fe3aeb31fcf41da2"


def read_csv(name: str) -> list[dict]:
    path = DATA_OUT / name
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


def main(*, raw_lineage: bool = False) -> int:
    checks: list[dict] = []

    def check(name: str, condition: bool, observed, expected) -> None:
        checks.append({
            "check": name, "status": "PASS" if condition else "FAIL",
            "observed": str(observed), "expected": str(expected),
        })

    raw = read_csv("points_raw.csv")
    corrections = read_csv("source_corrections.csv")
    geocoded = read_csv("points_geocoded.csv")
    failed = read_csv("geocode_failed.csv")
    outlets = read_csv("outlets_validated.csv")
    clusters = read_csv("coordinate_clusters_5m.csv")
    reverse_audit = read_csv("geocode_reverse_audit.csv")
    access = read_csv("access_jeonbuk.csv")
    road = read_csv("access_road.csv")
    metadata = json.loads((DATA_OUT / "roadnet_metadata.json").read_text(encoding="utf-8"))
    typology = read_csv("access_typology.csv")
    typology_metadata = json.loads(
        (DATA_OUT / "typology_evaluation.json").read_text(encoding="utf-8")
    )
    jeonbuk_venues = read_csv("venues_jeonbuk.csv")
    jeonbuk_venue_failures = read_csv("venues_jeonbuk_geocode_failed.csv")
    jeonbuk_venue_metadata = json.loads(
        (DATA_OUT / "venues_jeonbuk_metadata.json").read_text(encoding="utf-8")
    )
    route_scenario = json.loads(
        (DATA_OUT / "jeonbuk_route_scenario.json").read_text(encoding="utf-8")
    )
    scenario_evidence = json.loads(
        (DATA_OUT / "scenario_evidence.json").read_text(encoding="utf-8")
    )
    source_manifest = json.loads(
        (ROOT / "data" / "source_manifest.json").read_text(encoding="utf-8")
    )
    ecos_rows = read_csv("ecos_jeonbuk_loans_202508_202605.csv")
    ecos_metadata = json.loads(
        (DATA_OUT / "ecos_jeonbuk_loans_metadata.json").read_text(encoding="utf-8")
    )

    check("raw_outlet_count", len(raw) == 681, len(raw), 681)
    type_counts = Counter(r["type"] for r in raw)
    check("raw_type_counts", dict(type_counts) == EXPECTED_TYPES, dict(type_counts), EXPECTED_TYPES)
    check("raw_outlet_id_unique", len({r["outlet_id"] for r in raw}) == len(raw),
          len({r["outlet_id"] for r in raw}), len(raw))
    check("raw_exact_key_unique", len({(r["type"], r["name"], r["addr"]) for r in raw}) == len(raw),
          len({(r["type"], r["name"], r["addr"]) for r in raw}), len(raw))
    check("source_snapshot_complete", all(r["source_snapshot"] for r in raw),
          sum(bool(r["source_snapshot"]) for r in raw), len(raw))
    corrected = [r for r in raw if r.get("source_correction_id")]
    check("source_correction_ledger", len(corrections) == 1 and len(corrected) == 1
          and corrected[0]["source_correction_id"] == corrections[0]["correction_id"]
          and corrected[0]["addr"] == "전북특별자치도 완주군 이서면 안전로 163",
          f"{len(corrections)}/{len(corrected)}/{corrected[0]['addr'] if corrected else ''}",
          "1/1/전북특별자치도 완주군 이서면 안전로 163")
    if raw_lineage:
        kfcc_rows = list(csv.DictReader(
            (DATA_RAW / "points" / "kfcc_mg_jeonbuk.csv")
            .read_text(encoding="utf-8-sig").splitlines()
        ))
        kfcc_metadata = json.loads(
            (DATA_RAW / "points" / "kfcc_collection_metadata.json")
            .read_text(encoding="utf-8")
        )
        kfcc_classes = Counter(row["분류"] for row in kfcc_rows)
        check("kfcc_public_scope_classes", len(kfcc_rows) == 141
              and kfcc_classes == {"지역": 136, "직장": 5},
              f"{len(kfcc_rows)}/{dict(kfcc_classes)}", "141/{'지역': 136, '직장': 5}")
        kfcc_regions = kfcc_metadata.get("regions", [])
        check("kfcc_end_element_assertions", len(kfcc_regions) == 14
              and kfcc_metadata.get("source_rows") == 141
              and kfcc_metadata.get("unique_name_address_rows") == 141
              and kfcc_metadata.get("all_endElement_matches") is True
              and all(row.get("endElement") == row.get("parsed_rows") and row.get("matched") is True
                      for row in kfcc_regions),
              f"regions={len(kfcc_regions)}, rows={kfcc_metadata.get('source_rows')}, "
              f"all={kfcc_metadata.get('all_endElement_matches')}",
              "14 regions, 141 rows, every endElement equals parsed_rows")

    check("geocode_partition", len(geocoded) + len(failed) == len(raw),
          f"{len(geocoded)}+{len(failed)}", len(raw))
    center_methods = [r for r in geocoded if "중심" in r["geo_how"]]
    check("no_admin_center_fallback", not center_methods, len(center_methods), 0)
    check("all_geocodes_inside_admin", all(r["geo_inside_jeonbuk"] == "Y" for r in geocoded),
          sum(r["geo_inside_jeonbuk"] == "Y" for r in geocoded), len(geocoded))
    if geocoded and "geo_matched_admin_match" in geocoded[0]:
        admin_conflicts = [r for r in geocoded
                           if r["geo_admin_match"] == "N" or r["geo_matched_admin_match"] == "N"]
        check("admin_conflicts_flagged",
              len(admin_conflicts) == 1
              and admin_conflicts[0]["geo_review"] == "verified_address_boundary_conflict"
              and admin_conflicts[0]["source_correction_id"] == "CORR-001",
              [(r["name"], r["geo_review"]) for r in admin_conflicts],
              "one verified address/boundary conflict")
    check("geocode_id_partition", {r["outlet_id"] for r in geocoded} | {r["outlet_id"] for r in failed}
          == {r["outlet_id"] for r in raw},
          len({r["outlet_id"] for r in geocoded} | {r["outlet_id"] for r in failed}), len(raw))

    check("validated_outlets_preserve_geocoded", {r["outlet_id"] for r in outlets}
          == {r["outlet_id"] for r in geocoded}, len(outlets), len(geocoded))
    check("eligible_outlet_count", sum(r["finance_open"] == "Y" for r in outlets) == 643,
          sum(r["finance_open"] == "Y" for r in outlets), 643)
    check("cluster_membership_total", sum(int(r["outlet_count"]) for r in clusters) == len(outlets),
          sum(int(r["outlet_count"]) for r in clusters), len(outlets))
    check("cluster_id_assigned", all(r["coord_cluster_5m"] for r in outlets),
          sum(bool(r["coord_cluster_5m"]) for r in outlets), len(outlets))
    audit_ids = {r["outlet_id"] for r in reverse_audit}
    required_audit_ids = {
        r["outlet_id"] for r in outlets
        if r["geo_quality"] == "place_name"
        or r["geo_admin_match"] == "N"
        or r["geo_matched_admin_match"] == "N"
        or not (35.0 <= float(r["lat"]) <= 36.2 and 126.3 <= float(r["lon"]) <= 127.9)
    }
    check("reverse_audit_required_cases", required_audit_ids <= audit_ids,
          len(required_audit_ids & audit_ids), len(required_audit_ids))
    check("reverse_audit_addresses_present", all(r["reverse_address_kakao"] for r in reverse_audit),
          sum(bool(r["reverse_address_kakao"]) for r in reverse_audit), len(reverse_audit))
    check("reverse_audit_status_consistent", all(
        (r["audit_status"] == "PASS") == (r["coord_sigungu_sgis"] == r["reverse_sigungu_kakao"])
        for r in reverse_audit
    ), Counter(r["audit_status"] for r in reverse_audit), "PASS iff sigungu matches")

    check("admin_access_count", len(access) == 243, len(access), 243)
    check("admin_code_unique", len({r["code"] for r in access}) == 243,
          len({r["code"] for r in access}), 243)
    check("population_65plus_total", sum(int(r["pop_65plus"]) for r in access) == EXPECTED_P65,
          sum(int(r["pop_65plus"]) for r in access), EXPECTED_P65)
    check("population_exposure_guard", all(r["population_exposure_valid"] == "N" for r in access),
          sum(r["population_exposure_valid"] == "N" for r in access), 243)

    if raw_lineage:
        geo = json.loads((DATA_RAW / "hjd2026.geojson").read_text(encoding="utf-8"))
        features = {
            feature["properties"]["adm_cd2"]: feature
            for feature in geo["features"]
            if feature["properties"].get("sido") == "52"
        }
        inside_count = sum(
            point_in_geometry(
                float(row["lon"]),
                float(row["lat"]),
                features[row["code"]]["geometry"],
            )
            for row in access
        )
        check("admin_points_inside_own_polygon", inside_count == 243, inside_count, 243)

    check("road_row_count", len(road) == 243, len(road), 243)
    routed = [r for r in road if r["road_km"]]
    valid_statuses = {"ok", "fallback_nearest_reachable", "admin_snap_failed",
                      "no_directed_path_to_eligible_outlet"}
    check("road_status_explicit", all(r["route_status"] in valid_statuses for r in road),
          sorted({r["route_status"] for r in road}), sorted(valid_statuses))
    check("road_all_outlet_algorithm", all(r["routing_method"] == "directed_all_outlet_reverse_multisource_dijkstra" for r in road),
          len({r["routing_method"] for r in road}), 1)
    check("road_no_candidate_cutoff", metadata["candidate_limit"] is None and metadata["cutoff_km"] is None,
          f"{metadata['candidate_limit']}/{metadata['cutoff_km']}", "None/None")
    check("road_keeps_components", metadata["components_removed"] == 0, metadata["components_removed"], 0)
    check("road_pbf_md5", metadata["pbf_md5"] == EXPECTED_PBF_MD5, metadata["pbf_md5"], EXPECTED_PBF_MD5)
    check("road_oneway", metadata["oneway_respected"] is True and all(r["oneway_respected"] == "Y" for r in road),
          metadata["oneway_respected"], True)
    check("road_numeric_coverage", len(routed) == 243, len(routed), 243)
    if road and "road_distance_primary" in road[0] and "primary_admin_points" in metadata:
        primary = [r for r in road if r["road_distance_primary"] == "Y"]
        fallback = [r for r in road if r["route_status"] == "fallback_nearest_reachable"]
        check("road_primary_flag",
              all((r["route_status"] == "ok") == (r["road_distance_primary"] == "Y") for r in road),
              len(primary), metadata["primary_admin_points"])
        check("road_fallback_disclosed", len(fallback) == metadata["fallback_admin_points"],
              len(fallback), metadata["fallback_admin_points"])
    component_errors = []
    detour_errors = []
    for r in routed:
        parts = float(r["admin_snap_km"]) + float(r["network_km"]) + float(r["outlet_snap_km"])
        if abs(parts - float(r["road_km"])) > 0.004:
            component_errors.append(r["code"])
        if r["detour"] and float(r["detour"]) < 0.995:
            detour_errors.append((r["code"], r["detour"]))
    check("road_component_sum", not component_errors, component_errors[:5], "none")
    check("road_not_shorter_than_direct", not detour_errors, detour_errors[:5], "none")

    check("typology_row_count", len(typology) == len(road), len(typology), len(road))
    check("typology_code_partition", {r["code"] for r in typology} == {r["code"] for r in road},
          len({r["code"] for r in typology}), len(road))
    current_road_hash = hashlib.sha256((DATA_OUT / "access_road.csv").read_bytes()).hexdigest()
    check("typology_input_hash", typology_metadata["input_sha256"] == current_road_hash,
          typology_metadata["input_sha256"], current_road_hash)
    assigned = [r for r in typology if r["typology_status"] == "assigned_exploratory"]
    assigned_clusters = {r["cluster_id"] for r in assigned}
    selected_model = typology_metadata.get("selected_model")
    accepted_model_valid = (
        selected_model is not None
        and selected_model["passes_project_gates"] is True
        and len(assigned_clusters) == selected_model["k"]
    )
    rejected_model_valid = (
        selected_model is None
        and not assigned
        and typology_metadata["model_status"] == "rejected_use_rule_based_typology"
    )
    check("typology_model_or_fallback_gate",
          accepted_model_valid or rejected_model_valid,
          f"selected={selected_model['k'] if selected_model else None}, clusters={len(assigned_clusters)}",
          "accepted model matches output, or rejected model emits rule-only fallback")
    sensitivity = typology_metadata.get("preprocessing_sensitivity")
    passing_models = [
        model for model in typology_metadata["candidate_models"]
        if model["passes_project_gates"]
    ]
    strongest_model = max(
        passing_models,
        key=lambda model: (model["silhouette"], -model["k"]),
    ) if passing_models else None
    sensitivity_valid = (
        sensitivity is not None
        and selected_model is not None
        and sensitivity["status"] == "adoption_gate"
        and sensitivity["adjusted_rand_index"]
        >= typology_metadata["project_gates"]["preprocessing_ari_min"]
        and min(match["jaccard"] for match in sensitivity["cluster_matches"])
        >= typology_metadata["project_gates"]["preprocessing_cluster_jaccard_min"]
        and len(sensitivity["cluster_matches"]) == selected_model["k"]
        and strongest_model is not None
        and selected_model["k"] == strongest_model["k"]
    ) if selected_model is not None else sensitivity is None
    check("typology_preprocessing_sensitivity",
          sensitivity_valid,
          f"ARI={sensitivity['adjusted_rand_index'] if sensitivity else None}, "
          f"clusters={len(sensitivity['cluster_matches']) if sensitivity else 0}",
          "adoption gate passes and strongest passing model is selected")
    feature_definitions = typology_metadata.get("feature_definitions", {})
    check("typology_mixed_distance_features_disclosed",
          "OSM" in feature_definitions.get("road_km", "")
          and "직선거리" in feature_definitions.get("cnt_3km", ""),
          feature_definitions,
          "road_km is network distance; cnt_3km is straight-line count")
    assignment_scope_valid = (
        len(assigned) == typology_metadata["fit_row_count"]
        and all(r["analysis_cohort"] == "rural_peer"
                and r["road_distance_primary"] == "Y" for r in assigned)
    ) if selected_model is not None else not assigned
    check("typology_fit_scope", assignment_scope_valid,
          len(assigned), typology_metadata["fit_row_count"])
    fallback_typology = [r for r in typology if r["typology_status"] == "excluded_route_quality"]
    check("typology_fallback_unassigned",
          len(fallback_typology) == typology_metadata["excluded"]["route_quality"]
          and all(not r["cluster_id"] and r["road_distance_primary"] == "N"
                  for r in fallback_typology),
          len(fallback_typology), typology_metadata["excluded"]["route_quality"])
    rural_typology = [r for r in typology if r["analysis_cohort"] == "rural_peer"]
    urban_typology = [r for r in typology if r["analysis_cohort"] == "urban_comparator"]
    check("typology_rule_fallback",
          all(r["rule_type"] for r in rural_typology)
          and all(not r["rule_type"] for r in urban_typology),
          f"rural={sum(bool(r['rule_type']) for r in rural_typology)}, "
          f"urban={sum(bool(r['rule_type']) for r in urban_typology)}",
          f"rural={len(rural_typology)}, urban=0")

    check("jeonbuk_venue_source_partition",
          len(jeonbuk_venues) + len(jeonbuk_venue_failures)
          == jeonbuk_venue_metadata["source_rows"] == 6880,
          f"{len(jeonbuk_venues)}+{len(jeonbuk_venue_failures)}",
          6880)
    check("jeonbuk_venue_id_unique",
          len({row["venue_id"] for row in jeonbuk_venues}) == len(jeonbuk_venues),
          len({row["venue_id"] for row in jeonbuk_venues}), len(jeonbuk_venues))
    check("jeonbuk_venue_province_coverage",
          len({row["source_sigungu"] for row in jeonbuk_venues}) == 14
          and len({row["coord_admin_code"] for row in jeonbuk_venues}) == 243
          and sum(row["source_sigungu_match"] == "Y" for row in jeonbuk_venues) == 6854,
          f"cities={len({row['source_sigungu'] for row in jeonbuk_venues})}, "
          f"admins={len({row['coord_admin_code'] for row in jeonbuk_venues})}, "
          f"matched={sum(row['source_sigungu_match'] == 'Y' for row in jeonbuk_venues)}",
          "14 cities, 243 admins, 6854 source/boundary matches")
    check("jeonbuk_venue_operational_guard",
          all(row["use_approval_status"] == "unverified"
              and row["time_window_status"] == "not_provided" for row in jeonbuk_venues),
          len(jeonbuk_venues), "every venue unverified / no source time window")
    published_venue_fields = (
        set(jeonbuk_venues[0]) if jeonbuk_venues else set()
    ) | (
        set(jeonbuk_venue_failures[0]) if jeonbuk_venue_failures else set()
    )
    check("jeonbuk_venue_privacy_contract",
          jeonbuk_venue_metadata["source_contains_phone"] is False
          and not {"전화번호", "phone", "tel"} & published_venue_fields,
          sorted(published_venue_fields),
          "official source and published outputs contain no phone field")

    route_hash_sources = {
        "access_road_sha256": DATA_OUT / "access_road.csv",
        "access_typology_sha256": DATA_OUT / "access_typology.csv",
        "venues_jeonbuk_sha256": DATA_OUT / "venues_jeonbuk.csv",
        "outlets_validated_sha256": DATA_OUT / "outlets_validated.csv",
        "scenario_config_sha256": DATA_OUT.parent.parent / "config" / "jeonbuk_route_default.json",
    }
    observed_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in route_hash_sources.items()
    }
    check("route_scenario_input_hashes",
          route_scenario["input_hashes"] == observed_hashes,
          route_scenario["input_hashes"], observed_hashes)
    route_input = route_scenario["engine_input"]
    matrix_node_count = 0
    matrix_complete = True
    for zone in route_input["zones"]:
        engine = zone["engine_input"]
        route_node_ids = {
            engine["start_node_id"], engine["end_node_id"],
            *[row["candidate_id"] for row in engine["candidates"]],
        }
        matrix_node_count += len(route_node_ids)
        matrix_complete = matrix_complete and all(
            set(engine["distance_km"].get(node_id, {})) == route_node_ids
            and set(engine["travel_minutes"].get(node_id, {})) == route_node_ids
            for node_id in route_node_ids
        )
    check("route_scenario_matrix_complete", matrix_complete,
          matrix_node_count, "complete directed matrix within every service zone")
    route_targets = [
        target for zone in route_input["zones"]
        for target in zone["engine_input"]["targets"]
    ]
    route_candidates = [
        candidate for zone in route_input["zones"]
        for candidate in zone["engine_input"]["candidates"]
    ]
    check("route_scenario_scope",
          route_scenario["scope"] == {
              "analysis_admin_count": 243,
              "analysis_service_zone_count": 14,
              "threshold_target_count": 71,
              "route_eligible_target_count": 69,
              "route_quality_deferred_count": 2,
              "candidate_count": 69,
          }
          and len(route_input["zones"]) == 14
          and len(route_targets) == len({row["target_id"] for row in route_targets}) == 69
          and len(route_candidates) == 69
          and {row["candidate_id"] for row in route_candidates}
          <= {row["venue_id"] for row in jeonbuk_venues},
          route_scenario["scope"],
          "243 admins, 14 zones, 71 threshold, 69 route targets/candidates, 2 deferred")
    recomputed_route_results = solve_province(route_input)
    check("route_scenario_deterministic_recompute",
          route_scenario["results"] == recomputed_route_results,
          route_scenario["results"]["optimized"]["covered_target_count"],
          recomputed_route_results["optimized"]["covered_target_count"])
    check("route_scenario_priority_improvement",
          route_scenario["results"]["comparison"]["coverage_by_tier_delta"]["P1"] == 4
          and route_scenario["results"]["optimized"]["coverage_by_tier"]["P1"] == 26
          and route_scenario["results"]["optimized"]["covered_target_count"] == 57,
          route_scenario["results"]["comparison"]["coverage_by_tier_delta"],
          "P1 +4 and all 26 eligible P1 covered at total coverage 57")
    zone_allocations = route_scenario["results"]["zone_allocations"]
    check("route_scenario_zone_fairness",
          len(zone_allocations) == 14
          and all(row["allocated_route_days"] >= 1 for row in zone_allocations)
          and sum(row["allocated_route_days"] for row in zone_allocations) == 15,
          [(row["zone_id"], row["allocated_route_days"]) for row in zone_allocations],
          "all 14 zones receive at least one of 15 route-days")
    attachment_rows = [
        row
        for rows in route_scenario["travel_model"]["attachments_by_zone"].values()
        for row in rows
    ]
    attachment_fallbacks = [
        row for row in attachment_rows
        if row["snap_strategy"] == "nearest_mutually_reachable_node_fallback"
    ]
    check("route_scenario_attachment_quality",
          len(attachment_rows) == 83
          and len(attachment_fallbacks) == 1
          and float(attachment_fallbacks[0]["connector_km"]) < 0.05,
          f"nodes={len(attachment_rows)}, fallbacks={attachment_fallbacks}",
          "83 nodes; one disclosed mutually-reachable fallback below 0.05km")
    check("route_scenario_operational_guard",
          route_scenario["operational_ready"] is False
          and route_scenario["status"] == "demonstration_not_operational"
          and route_scenario["travel_model"]["actual_traffic_time"] is False
          and route_scenario["travel_model"]["interzone_repositioning_modeled"] is False
          and all(
              depot["confirmation_status"] == "unverified_as_operational_depot"
              for pair in route_scenario["depots_by_zone"].values()
              for depot in pair.values()
          ),
          route_scenario["status"],
          "demonstration only; depot/traffic/repositioning not operationally verified")
    measurement = route_scenario.get("measurement_contract", {})
    check("route_scenario_measurement_contract",
          measurement.get("resident_coverage_available") is False
          and measurement.get("population_exposure_valid") is False
          and measurement.get("candidate_location_optimization_performed") is False
          and measurement.get("every_candidate_serves_exactly_one_target") is True,
          measurement,
          "visits are admin-target proxies; no resident coverage or location optimization")
    optimized_temporal = route_scenario["results"]["optimized"]["temporal_access"]
    check("route_scenario_temporal_access",
          route_input["service_cycle_days"] == 7
          and optimized_temporal["service_cycle_days"] == 7
          and optimized_temporal["route_day_capacity"] == 15
          and route_scenario["results"]["optimized"]["route_days_used"] == 15
          and max(row["cycle_day"] for row in route_scenario["results"]["optimized"]["routes"]) == 5
          and optimized_temporal["covered_target_max_wait_days_upper_bound"] == 7
          and optimized_temporal["unvisited_targets_have_scheduled_service"] is False,
          optimized_temporal,
          "3 vehicles x 5 days in a 7-day cycle; unvisited targets remain unscheduled")

    evidence_hashes = {
        "access_road_sha256": hashlib.sha256(
            (DATA_OUT / "access_road.csv").read_bytes()
        ).hexdigest(),
        "outlets_validated_sha256": hashlib.sha256(
            (DATA_OUT / "outlets_validated.csv").read_bytes()
        ).hexdigest(),
        "jeonbuk_route_scenario_sha256": hashlib.sha256(
            (DATA_OUT / "jeonbuk_route_scenario.json").read_bytes()
        ).hexdigest(),
        "scenario_config_sha256": hashlib.sha256(
            (ROOT / "config" / "jeonbuk_route_default.json").read_bytes()
        ).hexdigest(),
    }
    check("scenario_evidence_input_hashes",
          scenario_evidence["input_hashes"] == evidence_hashes,
          scenario_evidence["input_hashes"], evidence_hashes)
    stop_rows = scenario_evidence["stop_cap_sensitivity"]
    speed_rows = scenario_evidence["speed_service_sensitivity"]
    check("scenario_evidence_scope_and_semantics",
          scenario_evidence["scope"] == {
              "analysis_admin_count": 243,
              "analysis_service_zone_count": 14,
              "route_eligible_admin_target_count": 69,
          }
          and scenario_evidence["metric_contract"]["resident_coverage_available"] is False
          and scenario_evidence["default_scenario"]["visited_admin_target_count"] == 57,
          scenario_evidence["scope"],
          "243 admins, 14 zones, 69 eligible targets; 57 visits, no resident coverage")
    check("scenario_evidence_stop_cap_dependence",
          [row["visited_admin_target_count"] for row in stop_rows]
          == [15, 30, 45, 57, 63, 68, 68]
          and all(row["visit_count_by_tier"]["P1"] <= 26 for row in stop_rows),
          [row["visited_admin_target_count"] for row in stop_rows],
          "15/30/45/57/63/68/68 visits for stop caps 1..7")
    check("scenario_evidence_speed_service_grid",
          len(speed_rows) == 9
          and {row["visited_admin_target_count"] for row in speed_rows} == {57},
          f"rows={len(speed_rows)}, visits={sorted({row['visited_admin_target_count'] for row in speed_rows})}",
          "9 combinations; 57 visits under the fixed stop cap")

    source_rows = source_manifest.get("sources", [])
    source_ids = [row.get("source_id") for row in source_rows]
    check("source_manifest_contract",
          len(source_rows) == 10
          and len(set(source_ids)) == len(source_ids)
          and all(str(row.get("source_page_url", "")).startswith("https://")
                  and row.get("retrieved_on")
                  and row.get("license_or_terms")
                  and row.get("model_role") for row in source_rows),
          f"rows={len(source_rows)}, unique={len(set(source_ids))}",
          "10 unique sources with URL, retrieval date, terms, and model role")
    expected_source_ids = {
        "sgis_admin_boundaries_20260701",
        "mois_age_sex_20260630",
        "koreapost_offices_20250301",
        "kfb_jeonbuk_branches_202512",
        "cu_jeonbuk_search_20260810",
        "kfcc_jeonbuk_20260811",
        "osm_south_korea_20260811",
        "kakao_local_geocoding_20260811",
        "jeonbuk_senior_centers_20241231",
        "ecos_141Y003_202508_202605",
    }
    check("source_manifest_expected_sources",
          set(source_ids) == expected_source_ids,
          sorted(source_ids), sorted(expected_source_ids))
    tracked_snapshot_errors = []
    raw_snapshot_errors = []
    for source in source_rows:
        path = ROOT / source["local_file"]
        is_raw = path.is_relative_to(DATA_RAW)
        if is_raw and not raw_lineage:
            continue
        if not path.is_file():
            (raw_snapshot_errors if is_raw else tracked_snapshot_errors).append(
                f"{source['source_id']}:missing"
            )
            continue
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        observed_bytes = path.stat().st_size
        errors = raw_snapshot_errors if is_raw else tracked_snapshot_errors
        if observed_hash != source["snapshot_sha256"]:
            errors.append(f"{source['source_id']}:sha256")
        if observed_bytes != source["snapshot_bytes"]:
            errors.append(f"{source['source_id']}:bytes")
        auxiliary = source.get("auxiliary_file")
        if auxiliary and raw_lineage:
            auxiliary_path = ROOT / auxiliary
            if not auxiliary_path.is_file() or hashlib.sha256(
                auxiliary_path.read_bytes()
            ).hexdigest() != source["auxiliary_sha256"]:
                raw_snapshot_errors.append(f"{source['source_id']}:auxiliary")
    check("source_manifest_tracked_snapshot_hashes",
          not tracked_snapshot_errors, tracked_snapshot_errors, "none")
    if raw_lineage:
        check("source_manifest_raw_snapshot_hashes",
              not raw_snapshot_errors, raw_snapshot_errors, "none")

    check("ecos_public_snapshot_contract",
          len(ecos_rows) == ecos_metadata["row_count"] == 10
          and ecos_rows[0]["time"] == "202508"
          and ecos_rows[-1]["time"] == "202605"
          and ecos_rows[-1]["value_billion_krw"] == "38420.9"
          and ecos_metadata["query"]["item_code"] == "200000"
          and ecos_metadata["query"]["region_code"] == "Q00"
          and ecos_metadata["usage"].endswith("not a model input"),
          f"rows={len(ecos_rows)}, last={ecos_rows[-1] if ecos_rows else None}",
          "10 official public-sample rows through 202605; context only")

    demo = json.loads((DATA_OUT / "jeongeup_demo.json").read_text(encoding="utf-8"))
    demo_posts = json.loads((DATA_OUT / "jeongeup_post.json").read_text(encoding="utf-8"))
    demo_geom = json.loads((DATA_OUT / "jeongeup_geom.json").read_text(encoding="utf-8"))
    jeongeup_access = {r["code"]: r for r in access if r["sigungu"] == "정읍시"}
    check("jeongeup_snapshot_counts",
          len(demo["dongs"]) == 23 and len(demo_posts) == 19 and len(demo_geom) == 23,
          f"{len(demo['dongs'])}/{len(demo_posts)}/{len(demo_geom)}", "23/19/23")
    check("jeongeup_no_center_or_failed_geocodes",
          all("중심" not in r["src"] and r["src"] != "실패" for r in demo_posts),
          sorted({r["src"] for r in demo_posts}), "address/place only")
    check("jeongeup_post_ids_valid",
          {r["outlet_id"] for r in demo_posts} <= {r["outlet_id"] for r in outlets},
          len({r["outlet_id"] for r in demo_posts}), 19)
    check("jeongeup_distances_match_master", all(
        math.isclose(float(r["d"]), float(jeongeup_access[r["code"]]["nearest_km"]), abs_tol=1e-9)
        for r in demo["dongs"]
    ), len(demo["dongs"]), 23)
    check("jeongeup_population_guard", demo["metadata"]["population_exposure_valid"] is False
          and all(r["population_exposure_valid"] is False for r in demo["dongs"]),
          demo["metadata"]["population_exposure_valid"], False)

    output_name = (
        "validation_raw_lineage_checks.csv" if raw_lineage else "validation_checks.csv"
    )
    out = DATA_OUT / output_name
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["check", "status", "observed", "expected"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(checks)

    failed_checks = [row for row in checks if row["status"] == "FAIL"]
    for row in checks:
        print(f"{row['status']:4s} {row['check']}: {row['observed']}")
    print(f"\n{len(checks) - len(failed_checks)}/{len(checks)} checks PASS → {out}")
    return 1 if failed_checks else 0


if __name__ == "__main__":
    unknown = set(sys.argv[1:]) - {"--raw-lineage"}
    if unknown:
        raise SystemExit(f"unknown arguments: {', '.join(sorted(unknown))}")
    sys.exit(main(raw_lineage="--raw-lineage" in sys.argv[1:]))
