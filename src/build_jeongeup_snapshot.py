"""Rebuild Jeongeup JSON data snapshots from the validated master datasets.

This replaces the early prototype files that contained failed foreign-city
geocodes and eup/myeon center fallbacks.  It does not edit the HTML demo.
"""

from __future__ import annotations

import csv
import json
import sys

from config import ROOT, DATA_RAW, DATA_OUT
from geo_utils import iter_polygons


def read_csv(name: str) -> list[dict]:
    return list(csv.DictReader((DATA_OUT / name).read_text(encoding="utf-8-sig").splitlines()))


def main() -> int:
    outlets = read_csv("outlets_validated.csv")
    by_id = {row["outlet_id"]: row for row in outlets}
    access = [row for row in read_csv("access_jeonbuk.csv") if row["sigungu"] == "정읍시"]
    road = {row["code"]: row for row in read_csv("access_road.csv") if row["sigungu"] == "정읍시"}
    posts = [row for row in outlets if row["type"] == "우체국" and row["coord_sigungu"] == "정읍시"]
    if len(access) != 23 or len(road) != 23 or len(posts) != 19:
        raise RuntimeError(f"정읍 기대값 불일치: access={len(access)}, road={len(road)}, posts={len(posts)}")

    post_rows = []
    for row in sorted(posts, key=lambda item: item["name"]):
        post_rows.append({
            "outlet_id": row["outlet_id"], "name": row["name"], "addr": row["addr"],
            "fin": row["detail"], "finance_status": row["finance_status"],
            "finance_open": row["finance_open"], "lat": float(row["lat"]), "lon": float(row["lon"]),
            "src": row["geo_how"], "geo_matched": row["geo_matched"],
            "source_snapshot": row["source_snapshot"],
        })

    dong_rows = []
    for row in sorted(access, key=lambda item: item["code"]):
        nearest = by_id[row["nearest_outlet_id"]]
        route = road[row["code"]]
        dong_rows.append({
            "code": row["code"], "name": row["dong"],
            "lon": float(row["lon"]), "lat": float(row["lat"]),
            "point_method": row["point_method"], "admin_area_km2": float(row["admin_area_km2"]),
            "p65": int(row["pop_65plus"]), "pop": int(row["pop_total"]),
            "d": float(row["nearest_km"]), "near": row["nearest_name"],
            "near_id": row["nearest_outlet_id"], "near_type": row["nearest_type"],
            "near_status": nearest["finance_status"],
            "fin": nearest["detail"] if nearest["type"] == "우체국" else nearest["finance_status"],
            "road_km": float(route["road_km"]), "road_near": route["road_nearest_name"],
            "road_near_id": route["road_outlet_id"],
            "road_distance_primary": route["road_distance_primary"],
            "population_exposure_valid": False,
        })

    geo = json.loads((DATA_RAW / "hjd2026.geojson").read_text(encoding="utf-8"))
    geometry = {}
    for feature in geo["features"]:
        props = feature["properties"]
        if props.get("sido") != "52" or props.get("sggnm") != "정읍시":
            continue
        rings = []
        for polygon in iter_polygons(feature["geometry"]):
            if polygon:
                rings.append([[round(float(p[0]), 5), round(float(p[1]), 5)] for p in polygon[0]])
        geometry[props["adm_cd2"]] = rings
    if set(geometry) != {row["code"] for row in access}:
        raise RuntimeError("정읍 경계와 접근성 행정동 키가 다름")

    metadata = {
        "generated_date": "2026-08-11",
        "dong_count": len(dong_rows), "post_office_count": len(post_rows),
        "outlet_scope": "all finance_open=Y outlet types for nearest distance",
        "straight_distance_model": "largest polygon interior representative point",
        "road_distance_source": "access_road.csv",
        "population_exposure_valid": False,
    }
    demo = {"metadata": metadata, "dongs": dong_rows, "posts": post_rows, "geom": geometry}
    (DATA_OUT / "jeongeup_post.json").write_text(
        json.dumps(post_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (DATA_OUT / "jeongeup_geom.json").write_text(
        json.dumps(geometry, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (DATA_OUT / "jeongeup_demo.json").write_text(
        json.dumps(demo, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (DATA_OUT / "jeongeup_snapshot_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"정읍 JSON 재생성: 행정동 {len(dong_rows)}, 우체국 {len(post_rows)}, 경계 {len(geometry)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
