"""Build auditable outlet and administrative-area access datasets.

This stage never deletes an outlet merely because another outlet is nearby.
It creates a separate 5 m coordinate-proximity cluster for diagnostics, then
computes straight-line distances from one interior representative point per
administrative dong.  Those distances are a geographic proxy, not a resident-
level exposure measure.

Outputs
  data/processed/outlets_validated.csv
  data/processed/coordinate_clusters_5m.csv
  data/processed/access_jeonbuk.csv
  reports/quality_report.md
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
from collections import Counter

from config import ROOT, DATA_RAW, DATA_OUT
from geo_utils import iter_polygons, point_in_geometry, representative_point

GEOJSON = DATA_RAW / "hjd2026.geojson"
POP_CSV = DATA_RAW / "mois_haengjeongdong_age_sex_20260630.csv"
POINTS_RAW = DATA_OUT / "points_raw.csv"
POINTS_GEOCODED = DATA_OUT / "points_geocoded.csv"
GEOCODE_FAILED = DATA_OUT / "geocode_failed.csv"
CLUSTER_METERS = 5.0
RADII_KM = (1.0, 3.0, 5.0)
TYPES = ("우체국", "은행", "신협", "새마을금고")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p = math.radians
    dlat, dlon = p(lat2 - lat1), p(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _ring_area_km2(ring) -> float:
    if len(ring) < 4:
        return 0.0
    mean_lat = sum(float(c[1]) for c in ring) / len(ring)
    lon_scale = 111.320 * math.cos(math.radians(mean_lat))
    lat_scale = 110.574
    twice = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = float(ring[i][0]) * lon_scale, float(ring[i][1]) * lat_scale
        x1, y1 = float(ring[i + 1][0]) * lon_scale, float(ring[i + 1][1]) * lat_scale
        twice += x0 * y1 - x1 * y0
    return abs(twice) / 2.0


def geometry_area_km2(geom: dict) -> float:
    area = 0.0
    for polygon in iter_polygons(geom):
        if not polygon:
            continue
        area += _ring_area_km2(polygon[0])
        area -= sum(_ring_area_km2(hole) for hole in polygon[1:])
    return max(0.0, area)


def load_csv(path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


def load_points() -> list[dict]:
    rows = load_csv(POINTS_GEOCODED)
    for row in rows:
        row["lat"] = float(row["lat"])
        row["lon"] = float(row["lon"])
    return rows


def load_population() -> dict[str, tuple[int, int]]:
    rows = list(csv.reader(io.StringIO(POP_CSV.read_bytes().decode("cp949"))))
    header = rows[0]
    idx65 = [
        i for i, col in enumerate(header)
        if any(col.startswith(f"{age}세") for age in range(65, 111)) or col.startswith("110세이상")
    ]
    if len(idx65) != 92:
        raise RuntimeError(f"65세 이상 연령·성별 컬럼은 92개여야 하나 {len(idx65)}개임")
    out: dict[str, tuple[int, int]] = {}
    for row in rows[1:]:
        if len(row) <= 5 or not row[0].startswith("52"):
            continue
        p65 = sum(int((row[i] or "0").replace(",", "")) for i in idx65 if row[i].strip())
        total = int((row[5] or "0").replace(",", ""))
        if row[0] in out:
            raise RuntimeError(f"인구 키 중복: {row[0]}")
        out[row[0]] = (p65, total)
    return out


def coordinate_clusters(points: list[dict]) -> tuple[list[dict], list[dict]]:
    """Attach 5 m proximity IDs without interpreting a cluster as one outlet."""
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # A 0.001 degree coarse grid is roughly 90-111 m in Jeonbuk.  Only nearby
    # cells need an exact haversine check.
    grid: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(points):
        key = (math.floor(p["lat"] * 1000), math.floor(p["lon"] * 1000))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in grid.get((key[0] + dy, key[1] + dx), []):
                    q = points[j]
                    if haversine(p["lat"], p["lon"], q["lat"], q["lon"]) * 1000 <= CLUSTER_METERS:
                        union(i, j)
        grid.setdefault(key, []).append(i)

    groups: dict[int, list[int]] = {}
    for i in range(len(points)):
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=lambda ids: min(points[i]["outlet_id"] for i in ids))

    cluster_rows = []
    for seq, ids in enumerate(ordered, 1):
        cid = f"CL5-{seq:04d}"
        members = sorted((points[i] for i in ids), key=lambda p: p["outlet_id"])
        for p in members:
            p["coord_cluster_5m"] = cid
            p["coord_cluster_size"] = len(members)
        cluster_rows.append({
            "coord_cluster_5m": cid,
            "cluster_lat": round(sum(p["lat"] for p in members) / len(members), 7),
            "cluster_lon": round(sum(p["lon"] for p in members) / len(members), 7),
            "outlet_count": len(members),
            "type_count": len({p["type"] for p in members}),
            "types": " | ".join(sorted({p["type"] for p in members})),
            "outlet_ids": " | ".join(p["outlet_id"] for p in members),
            "outlet_names": " | ".join(p["name"] for p in members),
            "definition": "connected by <=5m coordinate links; not a deduplication or verified building",
        })
    return points, cluster_rows


def write_outlets(points: list[dict], clusters: list[dict]) -> None:
    out_fields = [
        "outlet_id", "type", "name", "addr", "sigungu", "sigungu_src", "detail",
        "finance_open", "finance_status", "status_basis", "lat", "lon", "geo_how",
        "geo_quality", "geo_matched", "geo_matched_sigungu", "coord_admin_code", "coord_sigungu",
        "coord_dong", "geo_inside_jeonbuk", "geo_admin_match", "geo_matched_admin_match",
        "geo_review", "coord_cluster_5m",
        "coord_cluster_size", "source_correction_id", "source", "source_snapshot",
    ]
    with (DATA_OUT / "outlets_validated.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=out_fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(sorted(points, key=lambda p: p["outlet_id"]))
    with (DATA_OUT / "coordinate_clusters_5m.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(clusters[0].keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(clusters)


def nearest(lat: float, lon: float, pool: list[dict]) -> tuple[dict | None, float]:
    if not pool:
        return None, float("inf")
    best = min(pool, key=lambda p: haversine(lat, lon, p["lat"], p["lon"]))
    return best, haversine(lat, lon, best["lat"], best["lon"])


def write_quality_report(raw: list[dict], points: list[dict], failed: list[dict],
                         clusters: list[dict], results: list[dict]) -> None:
    open_points = [p for p in points if p["finance_open"] == "Y"]
    methods = Counter(p["geo_how"] for p in points)
    reviews = Counter(p["geo_review"] for p in points)
    statuses = Counter(p["finance_status"] for p in raw)
    type_raw = Counter(p["type"] for p in raw)
    type_geo = Counter(p["type"] for p in points)
    multi_clusters = [c for c in clusters if c["outlet_count"] > 1]
    cross_type = [c for c in multi_clusters if c["type_count"] > 1]
    proxy_over3 = sum(float(r["nearest_km"]) > 3 for r in results)
    proxy_over5 = sum(float(r["nearest_km"]) > 5 for r in results)

    lines = [
        "# 데이터 품질 리포트 — 전북 금융 접근성",
        "", "생성 기준일: 2026-08-11. 우체국 API 승인 전이므로 2026-08-10 공개 CSV 스냅샷을 사용했다.",
        "", "## 1. 접점 인벤토리", "",
        "| 구분 | 건수 | 해석 |", "|---|---:|---|",
        f"| 원천 점포 레코드 | {len(raw)} | 군사우편 1건은 수집 단계에서 제외 |",
        f"| 좌표 검증 통과 | {len(points)} | SGIS 전북 행정동 폴리곤 내부 |",
        f"| 좌표 미확정 | {len(failed)} | 시군·읍면 중심점으로 대체하지 않음 |",
        f"| 분석 가용 프록시 | {len(open_points)} | 목록 등재 또는 원천에 금융시간 기재 |",
        f"| 5m 좌표 근접 군집 | {len(clusters)} | 5m 이내 연결성분; 점포 수가 아닌 프록시 |",
        f"| 2개 이상 점포 군집 | {len(multi_clusters)} | 중복 삭제 안 함 |",
        f"| 이종 기관 군집 | {len(cross_type)} | 같은 건물임은 별도 확인 필요 |",
        "", "### 유형별 점포 레코드", "",
        "| 유형 | 원천 | 좌표 검증 |", "|---|---:|---:|",
    ]
    for typ in TYPES:
        lines.append(f"| {typ} | {type_raw[typ]} | {type_geo[typ]} |")
    lines += ["", "### 금융 상태 프록시", "", "| 상태 | 건수 |", "|---|---:|"]
    for status, count in sorted(statuses.items()):
        lines.append(f"| `{status}` | {count} |")
    lines += [
        "", "`listed_assumed_open`은 실시간 영업 확인이 아니라 공시 목록 등재를 분석 가용으로 간주한 것이다.",
        "", "## 2. 지오코딩 검증", "",
        "주소·장소명 검색 성공만 인정했고, 모든 성공 좌표를 SGIS 전북 243개 행정동 경계와 대조했다.",
        "전북 편의 bbox를 성공 조건으로 사용하지 않아 위도·어청도 좌표를 오류로 제외하지 않는다.",
        "", "| 방법 | 건수 |", "|---|---:|",
    ]
    for method, count in sorted(methods.items()):
        lines.append(f"| {method} | {count} |")
    lines += ["", "### 좌표 검토 플래그", "", "| 플래그 | 건수 |", "|---|---:|"]
    for review, count in sorted(reviews.items()):
        lines.append(f"| `{review}` | {count} |")
    conflicts = [p for p in points if "conflict" in p["geo_review"]]
    if conflicts:
        lines += [
            "", "정규화 주소·카카오 반환 주소와 SGIS 행정경계가 충돌하는 좌표는 자동 은폐하지 않고 별도 플래그로 남겼다.",
            "", "| ID | 점포 | 정규화 시군 | SGIS 시군 | 카카오 반환 시군 | 정정 장부 |", "|---|---|---|---|---|---|",
        ]
        for row in conflicts:
            lines.append(f"| {row['outlet_id']} | {row['name']} | {row['sigungu']} | {row['coord_sigungu']} | {row['geo_matched_sigungu']} | {row.get('source_correction_id', '') or '-'} |")
        lines += [
            "", "`CORR-001`은 은행연합회 원천의 `전주시 안전로 163`을 NH농협은행 공식 소재지 `완주군 이서면 안전로 163`으로 정정한 기록이다. 좌표는 해당 공식 주소와 일치하지만 SGIS 행정동 경계상 전주시로 판정되어 경계 충돌을 유지한다.",
        ]
    if failed:
        lines += ["", "### 좌표 미확정", "", "| ID | 유형 | 점포 | 사유 |", "|---|---|---|---|"]
        for row in failed:
            lines.append(f"| {row.get('outlet_id', '')} | {row['type']} | {row['name']} | {row.get('fail_reason', '')} |")
    lines += [
        "", "## 3. 행정동 접근성 프록시", "",
        f"- 행정동 {len(results)}개, 인구 조인 {len(results)}/{len(results)}, 65세 이상 합계 {sum(int(r['pop_65plus']) for r in results):,}명.",
        "- 대표점은 각 행정동의 최대 폴리곤 성분 내부에서 선정했다.",
        f"- 대표점 직선거리 3km 초과 {proxy_over3}개, 5km 초과 {proxy_over5}개.",
        "- **위 개수에 행정동 전체 65세+ 인구를 합산하지 않는다.** 행정동 대표점 거리는 거주지 분포를 반영하지 못한다.",
        "", "## 4. 접점 중복 처리", "",
        "- `(type, name, addr)`가 완전히 같은 원천 레코드만 수집 단계에서 중복으로 본다.",
        "- 25m 중복 제거는 사용하지 않는다. 같은 건물이어도 다른 지점명·유형이면 서로 다른 접점으로 보존한다.",
        f"- {CLUSTER_METERS:g}m 근접 군집은 물리 건물이나 동일 점포를 의미하지 않는 탐색용 필드다.",
        "", "## 5. 현재 판단 한계", "",
        "- 우체국: API 승인 전. 공개 CSV의 재건축·업무중지 문구 3건은 `suspended_unverified`로 분리했다.",
        "- 은행·신협·새마을금고: 공개 목록 스냅샷으로, 실시간 휴·폐점 상태를 보증하지 않는다.",
        "- 주민 단위 3km 초과 인구를 산출하려면 100m/500m 격자별 65세+ 인구가 추가로 필요하다.",
    ]
    report = ROOT / "reports" / "quality_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    raw = load_csv(POINTS_RAW)
    failed = load_csv(GEOCODE_FAILED)
    points, clusters = coordinate_clusters(load_points())
    write_outlets(points, clusters)

    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))
    dongs = [f for f in geo["features"] if f["properties"].get("sido") == "52"]
    population = load_population()
    codes = [f["properties"]["adm_cd2"] for f in dongs]
    if len(dongs) != 243 or len(set(codes)) != 243:
        raise RuntimeError(f"전북 행정동 경계는 243개여야 하나 {len(dongs)}개임")
    missing_pop = sorted(set(codes) - set(population))
    if missing_pop:
        raise RuntimeError(f"인구 미조인 키 {len(missing_pop)}개: {missing_pop[:5]}")

    open_points = [p for p in points if p["finance_open"] == "Y"]
    open_by_type = {typ: [p for p in open_points if p["type"] == typ] for typ in TYPES}
    results = []
    for feature in dongs:
        props = feature["properties"]
        rep = representative_point(feature["geometry"])
        if not rep:
            raise RuntimeError(f"대표점 산출 실패: {props['adm_cd2']} {props['adm_nm']}")
        lon, lat, point_method = rep
        if not point_in_geometry(lon, lat, feature["geometry"]):
            raise RuntimeError(f"대표점이 경계 밖임: {props['adm_cd2']}")
        p65, total = population[props["adm_cd2"]]
        near_open, dist_open = nearest(lat, lon, open_points)
        near_any, dist_any = nearest(lat, lon, points)
        row = {
            "code": props["adm_cd2"],
            "sigungu": props["sggnm"],
            "dong": props["adm_nm"].split()[-1],
            "lat": round(lat, 7), "lon": round(lon, 7),
            "point_method": point_method,
            "admin_area_km2": round(geometry_area_km2(feature["geometry"]), 3),
            "pop_total": total, "pop_65plus": p65,
            "ratio_65plus": round(p65 / total * 100, 1) if total else 0.0,
            "nearest_km": round(dist_open, 3),
            "nearest_outlet_id": near_open["outlet_id"],
            "nearest_name": near_open["name"], "nearest_type": near_open["type"],
            "nearest_open_km": round(dist_open, 3), "nearest_open_name": near_open["name"],
            "nearest_any_km": round(dist_any, 3), "nearest_any_outlet_id": near_any["outlet_id"],
            "nearest_any_name": near_any["name"], "nearest_any_type": near_any["type"],
            "distance_model": "largest_polygon_interior_point_straight_line",
            "distance_scope": "finance_open_proxy_Y",
            "population_exposure_valid": "N",
        }
        for typ in TYPES:
            _p, dist = nearest(lat, lon, open_by_type[typ])
            row[f"near_{typ}_km"] = round(dist, 3) if math.isfinite(dist) else ""
        for radius in RADII_KM:
            row[f"cnt_{radius:g}km"] = sum(
                haversine(lat, lon, p["lat"], p["lon"]) <= radius for p in open_points
            )
            row[f"cnt_any_{radius:g}km"] = sum(
                haversine(lat, lon, p["lat"], p["lon"]) <= radius for p in points
            )
        results.append(row)

    results.sort(key=lambda r: r["code"])
    out = DATA_OUT / "access_jeonbuk.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(results[0].keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(results)

    write_quality_report(raw, points, failed, clusters, results)
    print(f"접점: 원천 {len(raw)} / 좌표검증 {len(points)} / 미확정 {len(failed)} / 분석가용 {len(open_points)}")
    print(f"5m 좌표 군집 {len(clusters)}개 (점포 삭제 없음)")
    print(f"행정동 {len(results)}개 / 65세+ {sum(r['pop_65plus'] for r in results):,}명 / 인구노출 집계는 미산출")
    print(f"출력: {out.relative_to(ROOT)}, data/processed/outlets_validated.csv, reports/quality_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
