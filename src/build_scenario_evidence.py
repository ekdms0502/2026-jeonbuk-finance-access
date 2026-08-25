"""Build UI-neutral sensitivity and interpretation evidence for the route scenario."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from config import DATA_OUT, ROOT
from route_scenario import configure_province, solve_province


OUTPUT = DATA_OUT / "scenario_evidence.json"
REPORT = ROOT / "reports" / "scenario_evidence.md"
THRESHOLDS_KM = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
STOP_CAPS = range(1, 8)
SPEEDS_KMH = (30.0, 40.0, 50.0)
SERVICE_MINUTES = (30, 45, 60)


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA_OUT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def distribution(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 3),
        "median": round(percentile(values, 0.5), 3),
        "p90": round(percentile(values, 0.9), 3),
        "max": round(max(values), 3),
    }


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def service_zone(sigungu: str) -> str:
    return "전주시" if sigungu.startswith("전주시") else sigungu


def parameters(config: dict, *, service_minutes: int, max_stops: int) -> dict:
    return {
        "vehicle_count": int(config["vehicle_count"]),
        "operating_days_per_cycle": int(config["operating_days_per_cycle"]),
        "operating_start": config["operating_start"],
        "operating_end": config["operating_end"],
        "service_minutes": service_minutes,
        "max_stops_per_route": max_stops,
    }


def solve_summary(engine_input: dict, scenario_parameters: dict) -> dict:
    result = solve_province(configure_province(engine_input, scenario_parameters))["optimized"]
    return {
        "visited_admin_target_count": result["covered_target_count"],
        "visit_count_by_tier": result["coverage_by_tier"],
        "route_days_used": result["route_days_used"],
        "travel_km": result["totals"]["travel_km"],
        "max_route_elapsed_minutes": result["totals"]["max_route_elapsed_minutes"],
    }


def with_uniform_speed(engine_input: dict, speed_kmh: float) -> dict:
    adjusted = copy.deepcopy(engine_input)
    for zone in adjusted["zones"]:
        engine = zone["engine_input"]
        engine["travel_minutes"] = {
            origin: {
                destination: round(float(distance) / speed_kmh * 60, 6)
                for destination, distance in row.items()
            }
            for origin, row in engine["distance_km"].items()
        }
    return adjusted


def build_evidence() -> dict:
    route_path = DATA_OUT / "jeonbuk_route_scenario.json"
    access_path = DATA_OUT / "access_road.csv"
    outlet_path = DATA_OUT / "outlets_validated.csv"
    config_path = ROOT / "config" / "jeonbuk_route_default.json"
    route = json.loads(route_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    access = read_csv("access_road.csv")
    outlets = read_csv("outlets_validated.csv")
    outlet_by_id = {row["outlet_id"]: row for row in outlets}
    engine_input = route["engine_input"]
    target_ids = {
        target["target_id"]
        for zone in engine_input["zones"]
        for target in zone["engine_input"]["targets"]
    }
    candidates = [
        candidate
        for zone in engine_input["zones"]
        for candidate in zone["engine_input"]["candidates"]
    ]

    threshold_sensitivity = [
        {
            "road_km_gt": threshold,
            "all_admin_representative_points": sum(
                float(row["road_km"]) > threshold for row in access
            ),
            "primary_quality_admin_representative_points": sum(
                float(row["road_km"]) > threshold
                and row["road_distance_primary"] == "Y"
                for row in access
            ),
        }
        for threshold in THRESHOLDS_KM
    ]

    stop_cap_sensitivity = []
    for stop_cap in STOP_CAPS:
        scenario_parameters = parameters(
            config,
            service_minutes=int(config["service_minutes_default"]),
            max_stops=stop_cap,
        )
        stop_cap_sensitivity.append({
            "max_stops_per_route": stop_cap,
            **solve_summary(engine_input, scenario_parameters),
        })

    speed_service_sensitivity = []
    for speed in SPEEDS_KMH:
        adjusted = with_uniform_speed(engine_input, speed)
        for service_minutes in SERVICE_MINUTES:
            scenario_parameters = parameters(
                config,
                service_minutes=service_minutes,
                max_stops=int(config["max_stops_per_route"]),
            )
            speed_service_sensitivity.append({
                "uniform_speed_kmh": speed,
                "service_minutes": service_minutes,
                **solve_summary(adjusted, scenario_parameters),
            })

    eligible_outlets = [row for row in outlets if row["finance_open"] == "Y"]
    open_reported = [row for row in eligible_outlets if row["finance_status"] == "open_reported"]
    road_nearest_status = Counter(
        outlet_by_id[row["road_outlet_id"]]["finance_status"] for row in access
    )
    target_road_nearest_status = Counter(
        outlet_by_id[row["road_outlet_id"]]["finance_status"]
        for row in access
        if row["code"] in target_ids
    )

    def straight_threshold_counts(candidate_outlets: list[dict[str, str]]) -> dict[str, int]:
        nearest = []
        for admin in access:
            nearest.append(min(
                haversine(
                    float(admin["lat"]),
                    float(admin["lon"]),
                    float(outlet["lat"]),
                    float(outlet["lon"]),
                )
                for outlet in candidate_outlets
            ))
        return {
            "admin_representative_points_gt_3km": sum(value > 3 for value in nearest),
            "admin_representative_points_gt_5km": sum(value > 5 for value in nearest),
        }

    candidate_distances = [float(row["selection_distance_km"]) for row in candidates]
    longest_candidate = max(candidates, key=lambda row: float(row["selection_distance_km"]))
    default = route["results"]["optimized"]
    route_elapsed = [float(row["elapsed_minutes"]) for row in default["routes"]]

    return {
        "analysis_version": 1,
        "analysis_date": route["analysis_date"],
        "input_hashes": {
            "access_road_sha256": sha256(access_path),
            "outlets_validated_sha256": sha256(outlet_path),
            "jeonbuk_route_scenario_sha256": sha256(route_path),
            "scenario_config_sha256": sha256(config_path),
        },
        "scope": {
            "analysis_admin_count": len(access),
            "analysis_service_zone_count": len({service_zone(row["sigungu"]) for row in access}),
            "route_eligible_admin_target_count": len(target_ids),
        },
        "metric_contract": {
            "optimized_count_meaning": "visited administrative representative-point targets",
            "resident_coverage_available": False,
            "resident_coverage_reason": (
                "resident-level or 100m/500m age-grid origins are not available in the committed evidence"
            ),
            "population_exposure_valid": False,
            "candidate_location_optimization_performed": False,
            "candidate_contract": (
                "one nearest same-admin senior-center proxy per eligible admin target"
            ),
        },
        "default_scenario": {
            "status": route["status"],
            "operational_ready": route["operational_ready"],
            "visited_admin_target_count": default["covered_target_count"],
            "eligible_admin_target_count": len(target_ids),
            "visit_count_by_tier": default["coverage_by_tier"],
            "route_days_used": default["route_days_used"],
            "travel_km": default["totals"]["travel_km"],
            "wait_minutes": default["totals"]["wait_minutes"],
        },
        "threshold_sensitivity": threshold_sensitivity,
        "stop_cap_sensitivity": stop_cap_sensitivity,
        "speed_service_sensitivity": speed_service_sensitivity,
        "outlet_status_sensitivity": {
            "eligible_outlet_status_counts": dict(Counter(
                row["finance_status"] for row in eligible_outlets
            )),
            "road_nearest_status_counts_all_243": dict(road_nearest_status),
            "road_nearest_status_counts_route_targets": dict(target_road_nearest_status),
            "straight_line_all_eligible_statuses": straight_threshold_counts(eligible_outlets),
            "straight_line_open_reported_only": straight_threshold_counts(open_reported),
            "road_distance_open_reported_only_available": False,
        },
        "candidate_proxy_audit": {
            "candidate_count": len(candidates),
            "unique_candidate_count": len({row["candidate_id"] for row in candidates}),
            "every_candidate_serves_exactly_one_target": all(
                len(row["serves_target_ids"]) == 1 for row in candidates
            ),
            "selection_distance_km": distribution(candidate_distances),
            "longest_selection": {
                "candidate_id": longest_candidate["candidate_id"],
                "candidate_name": longest_candidate["name"],
                "target_id": longest_candidate["serves_target_ids"][0],
                "distance_km": float(longest_candidate["selection_distance_km"]),
            },
        },
        "route_duration_audit": {
            "operating_horizon_minutes": 480,
            "elapsed_minutes": distribution(route_elapsed),
            "all_routes_within_horizon": all(value <= 480 for value in route_elapsed),
        },
        "operational_gates": [
            "confirm actual depots and inter-municipality repositioning",
            "confirm venue permission, vehicle access, weekdays, and time windows",
            "calibrate travel time with observed traffic or field runs",
            "add resident-level or 100m/500m age-grid origins before claiming resident coverage",
        ],
    }


def write_report(evidence: dict) -> None:
    default = evidence["default_scenario"]
    candidate = evidence["candidate_proxy_audit"]
    duration = evidence["route_duration_audit"]
    lines = [
        "# 전북 순회 시나리오 민감도·효과 해석 감사",
        "",
        "## 결론",
        "",
        f"전북 14개 시군·243개 행정동 범위를 유지했다. 기본안의 `{default['visited_admin_target_count']}`은 "
        f"경로대상 {default['eligible_admin_target_count']}개 중 **방문하는 행정동 대표점 대상 수**다. "
        "주민 수나 주민 접근성 개선 인구를 뜻하지 않는다.",
        "",
        "- 주민 커버리지 산출 가능: `false`",
        "- 실제 운영 준비 완료: `false`",
        "- 후보 위치 최적화 수행: `false` — 대상별 같은 행정동의 최근접 경로당 1곳을 프록시로 연결",
        "",
        "## 대표점 도로거리 임계값 민감도",
        "",
        "| 임계값 초과 | 전체 대표점 | 주 도로거리 품질만 |",
        "|---:|---:|---:|",
    ]
    for row in evidence["threshold_sensitivity"]:
        lines.append(
            f"| {row['road_km_gt']:.1f}km | {row['all_admin_representative_points']} | "
            f"{row['primary_quality_admin_representative_points']} |"
        )

    lines += [
        "",
        "`3km`와 `5km`는 이 프로젝트의 비교 시나리오 분류선이며 공식 금융소외 기준이 아니다.",
        "",
        "## 1일 최대 방문 수 민감도",
        "",
        "차량 3대·주 5일·09:00~17:00·거점당 45분은 고정하고 경로당 최대 방문 수만 바꿨다.",
        "",
        "| 최대 방문/경로일 | 전체 방문 | P1 방문 | 경로일 | 이동거리 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in evidence["stop_cap_sensitivity"]:
        lines.append(
            f"| {row['max_stops_per_route']} | {row['visited_admin_target_count']} | "
            f"{row['visit_count_by_tier']['P1']} | {row['route_days_used']} | "
            f"{row['travel_km']:.1f}km |"
        )

    status = evidence["outlet_status_sensitivity"]
    lines += [
        "",
        "## 속도·서비스시간 교차 민감도",
        "",
        "| 속도 | 서비스시간 | 전체 방문 | P1 방문 | 최대 경로시간 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in evidence["speed_service_sensitivity"]:
        lines.append(
            f"| {row['uniform_speed_kmh']:.0f}km/h | {row['service_minutes']}분 | "
            f"{row['visited_admin_target_count']} | {row['visit_count_by_tier']['P1']} | "
            f"{row['max_route_elapsed_minutes']:.1f}분 |"
        )

    lines += [
        "",
        "현재 조합에서는 속도·서비스시간보다 최대 방문 수 제약이 결과를 더 강하게 제한한다. "
        "이는 운영값이 맞다는 증거가 아니라, 현장 확인에서 우선 검증할 가정이 무엇인지 보여준다.",
        "",
        "## 점포 상태·후보 프록시 감사",
        "",
        f"- 분석가용 접점 상태: `{status['eligible_outlet_status_counts']}`",
        f"- 243개 도로 최근접 접점 상태: `{status['road_nearest_status_counts_all_243']}`",
        f"- 69개 경로대상 도로 최근접 접점 상태: `{status['road_nearest_status_counts_route_targets']}`",
        f"- 직선거리 3km 초과: 전체 분석가용 상태 "
        f"{status['straight_line_all_eligible_statuses']['admin_representative_points_gt_3km']}개, "
        f"`open_reported`만 사용하면 "
        f"{status['straight_line_open_reported_only']['admin_representative_points_gt_3km']}개",
        "- `open_reported`만의 도로거리 재계산은 수행하지 않았으므로 제공하지 않는다.",
        f"- 후보-대표점 직선거리 최소/중앙/p90/최대: "
        f"{candidate['selection_distance_km']['min']:.3f}/"
        f"{candidate['selection_distance_km']['median']:.3f}/"
        f"{candidate['selection_distance_km']['p90']:.3f}/"
        f"{candidate['selection_distance_km']['max']:.3f}km",
        f"- 기본안 경로 소요시간 최소/중앙/최대: "
        f"{duration['elapsed_minutes']['min']:.1f}/"
        f"{duration['elapsed_minutes']['median']:.1f}/"
        f"{duration['elapsed_minutes']['max']:.1f}분",
        "",
        "## 사용 제한과 다음 운영 게이트",
        "",
    ]
    lines.extend(f"- {item}" for item in evidence["operational_gates"])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    evidence = build_evidence()
    OUTPUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(evidence)
    print(
        f"시나리오 증거: {evidence['scope']['analysis_admin_count']}개 행정동·"
        f"{len(evidence['threshold_sensitivity'])}개 임계값·"
        f"{len(evidence['stop_cap_sensitivity'])}개 방문상한·"
        f"{len(evidence['speed_service_sensitivity'])}개 속도×서비스 조합"
    )
    print(f"→ {OUTPUT.relative_to(ROOT)}, {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
