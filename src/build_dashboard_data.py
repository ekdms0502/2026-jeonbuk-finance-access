"""Build the compact, offline data bundle for the Jeonbuk dashboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
OUTPUT = ROOT / "docs" / "demo-jeonbuk" / "data.js"


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compact_outlets() -> tuple[list[dict], int]:
    listed = read_csv("outlets_validated.csv")
    outlets = []
    for row in listed:
        if row.get("finance_open") != "Y":
            continue
        if not row.get("lat") or not row.get("lon"):
            continue
        outlets.append({
            "type": row["type"],
            "name": row["name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "finance_open": row["finance_open"],
        })
    return outlets, len(listed)


def source_as_of() -> dict[str, str]:
    manifest = json.loads(
        (ROOT / "data" / "source_manifest.json").read_text(encoding="utf-8")
    )
    sources = {row["source_id"]: row for row in manifest["sources"]}
    outlet_ids = (
        "koreapost_offices_20250301",
        "kfb_jeonbuk_branches_202512",
        "cu_jeonbuk_search_20260810",
        "kfcc_jeonbuk_20260811",
    )
    outlet_as_of = [sources[source_id].get("as_of_date") for source_id in outlet_ids]
    outlet_retrieved = [sources[source_id].get("retrieved_on") for source_id in outlet_ids]
    return {
        "admin": sources["sgis_admin_boundaries_20260701"]["as_of_date"],
        "population_65plus": sources["mois_age_sex_20260630"]["as_of_date"],
        "outlets": min(date for date in outlet_as_of if date),
        "outlets_retrieved": max(date for date in outlet_retrieved if date),
        "generated_on": manifest["generated_on"],
    }


def service_zone(sigungu: str) -> str:
    return "전주시" if sigungu.startswith("전주시") else sigungu


def priority(row: dict[str, str]) -> str:
    road_km = float(row["road_km"])
    if row["road_distance_primary"] != "Y":
        return "quality_deferred" if road_km > 3 else "accessible"
    if road_km > 5:
        return "P1"
    if road_km > 3:
        return "P2"
    return "accessible"


def compact_engine(route: dict) -> dict:
    zones = []
    for zone in route["engine_input"]["zones"]:
        engine = zone["engine_input"]
        zones.append({
            "zone_id": zone["zone_id"],
            "engine_input": {
                "vehicle_count": 1,
                "max_stops_per_vehicle": engine["max_stops_per_vehicle"],
                "service_cycle_days": engine["service_cycle_days"],
                "operating_start": engine["operating_start"],
                "operating_end": engine["operating_end"],
                "start_node_id": engine["start_node_id"],
                "end_node_id": engine["end_node_id"],
                "priority_tiers": engine["priority_tiers"],
                "targets": [
                    {
                        "target_id": row["target_id"],
                        "name": row["name"],
                        "lat": row["lat"],
                        "lon": row["lon"],
                        "priority_tier": row["priority_tier"],
                    }
                    for row in engine["targets"]
                ],
                "candidates": [
                    {
                        "candidate_id": row["candidate_id"],
                        "name": row["name"],
                        "lat": row["lat"],
                        "lon": row["lon"],
                        "serves_target_ids": row["serves_target_ids"],
                        "service_minutes": row["service_minutes"],
                        "time_window_start": row["time_window_start"],
                        "time_window_end": row["time_window_end"],
                    }
                    for row in engine["candidates"]
                ],
                "distance_km": engine["distance_km"],
                "travel_minutes": engine["travel_minutes"],
            },
        })
    return {
        "vehicle_count": route["engine_input"]["vehicle_count"],
        "operating_days_per_cycle": route["engine_input"][
            "operating_days_per_cycle"
        ],
        "minimum_route_days_per_active_zone": route["engine_input"][
            "minimum_route_days_per_active_zone"
        ],
        "service_cycle_days": route["engine_input"]["service_cycle_days"],
        "priority_tiers": route["engine_input"]["priority_tiers"],
        "zones": zones,
    }


def build_payload() -> dict:
    access = read_csv("access_road.csv")
    typology = {row["code"]: row for row in read_csv("access_typology.csv")}
    if len(access) != 243 or set(typology) != {row["code"] for row in access}:
        raise RuntimeError("dashboard admin join must cover exactly 243 codes")

    route = json.loads(
        (DATA / "jeonbuk_route_scenario.json").read_text(encoding="utf-8")
    )
    scenario_evidence = json.loads(
        (DATA / "scenario_evidence.json").read_text(encoding="utf-8")
    )
    venue_metadata = json.loads(
        (DATA / "venues_jeonbuk_metadata.json").read_text(encoding="utf-8")
    )
    admins = []
    for row in access:
        type_row = typology[row["code"]]
        admins.append({
            "code": row["code"],
            "sigungu": row["sigungu"],
            "service_zone": service_zone(row["sigungu"]),
            "dong": row["dong"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "pop_total": int(row["pop_total"]),
            "pop_65plus": int(row["pop_65plus"]),
            "ratio_65plus": float(row["ratio_65plus"]),
            "road_km": float(row["road_km"]),
            "line_km": float(row["nearest_km"]),
            "road_distance_primary": row["road_distance_primary"],
            "route_quality": row["route_quality"],
            "nearest_name": row["road_nearest_name"],
            "nearest_type": row["road_nearest_type"],
            "cnt_3km": int(row["cnt_3km"]),
            "priority": priority(row),
            "cluster_label": type_row["cluster_label"],
            "rule_type": type_row["rule_type"],
            "typology_status": type_row["typology_status"],
        })
    admins.sort(key=lambda row: (row["service_zone"], row["dong"], row["code"]))
    outlets, listed_outlet_count = compact_outlets()

    return {
        "analysis_date": route["analysis_date"],
        "status": route["status"],
        "operational_ready": route["operational_ready"],
        "scope": route["scope"],
        "admins": admins,
        "input_controls": route["input_controls"],
        "sensitivity_presets": route["sensitivity_presets"],
        "measurement_contract": route["measurement_contract"],
        "evidence_summary": {
            "threshold_sensitivity": scenario_evidence["threshold_sensitivity"],
            "stop_cap_sensitivity": scenario_evidence["stop_cap_sensitivity"],
            "speed_service_sensitivity": scenario_evidence["speed_service_sensitivity"],
            "candidate_proxy_audit": scenario_evidence["candidate_proxy_audit"],
            "route_duration_audit": scenario_evidence["route_duration_audit"],
        },
        "route": {
            "engine_input": compact_engine(route),
            "depots_by_zone": route["depots_by_zone"],
            "excluded_targets": route["excluded_targets"],
            "travel_model": {
                key: route["travel_model"][key]
                for key in (
                    "distance",
                    "oneway_respected",
                    "time",
                    "uniform_speed_kmh",
                    "actual_traffic_time",
                    "interzone_repositioning_modeled",
                )
            },
            "input_hashes": route["input_hashes"],
        },
        "outlets": outlets,
        "source_as_of": source_as_of(),
        "source_summary": {
            "admin_count": len(admins),
            "finance_outlet_count": len(outlets),
            "finance_outlet_listed_count": listed_outlet_count,
            "senior_center_source_rows": venue_metadata["source_rows"],
            "senior_center_geocoded_rows": venue_metadata["geocoded_rows"],
            "senior_center_failed_rows": venue_metadata["failed_rows"],
            "road_primary_count": sum(
                row["road_distance_primary"] == "Y" for row in admins
            ),
        },
    }


def main() -> int:
    payload = build_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.write_text(
        "const JEONBUK_DASHBOARD=" + encoded + ";\n"
        "if(typeof window!==\"undefined\")window.JEONBUK_DASHBOARD=JEONBUK_DASHBOARD;\n"
        "if(typeof module!==\"undefined\")module.exports=JEONBUK_DASHBOARD;\n",
        encoding="utf-8",
    )
    print(
        f"전북 대시보드 데이터: {len(payload['admins'])}개 행정동·"
        f"{payload['source_summary']['finance_outlet_count']}개 분석가용 접점·"
        f"{payload['scope']['route_eligible_target_count']}개 경로대상"
    )
    print(f"→ {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
