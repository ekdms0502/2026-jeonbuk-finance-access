"""카카오 로컬 API로 접점 주소에 좌표를 부여하고 SGIS 경계로 검증한다.

폴백 체인: 정제주소 → 원본주소 → 번지 제거 도로명 → 기관명 장소검색.
읍면·시군 중심점은 점포 좌표가 아니므로 성공으로 인정하지 않는다.
결과는 data/processed/geocode_cache.json에 캐시하므로 재실행이 무료다.

출력  data/processed/points_geocoded.csv
      실패분 data/processed/geocode_failed.csv
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from config import ROOT, DATA_RAW, DATA_OUT, get_key
from geo_utils import geometry_bbox, point_in_geometry

API = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_API = "https://dapi.kakao.com/v2/local/search/keyword.json"
CACHE = DATA_OUT / "geocode_cache.json"
GEOJSON = DATA_RAW / "hjd2026.geojson"


def _load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def _call(url: str, params: dict, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"KakaoAK {key}"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:          # 쿼터/속도 제한
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(0.6)
    return None


def variants(addr_geo: str, addr: str, sigungu: str) -> list[tuple[str, str]]:
    """(질의문자열, 방법라벨) 목록 — 앞에서부터 시도."""
    out = [(addr_geo, "정제주소")]
    if addr != addr_geo:
        out.append((addr, "원본주소"))
    # 번지/호수 제거한 도로명까지
    m = re.match(r"(.*?(?:로|길)\s*\d+)", addr_geo)
    if m and m.group(1) != addr_geo:
        out.append((m.group(1), "도로명번지"))
    seen, uniq = set(), []
    for q, how in out:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            uniq.append((q, how))
    return uniq


def _admin_features() -> list[tuple[tuple[float, float, float, float], dict]]:
    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))
    out = []
    for feature in geo["features"]:
        if feature["properties"].get("sido") != "52":
            continue
        out.append((geometry_bbox(feature["geometry"]), feature))
    return out


def _admin_at(lon: float, lat: float, features) -> dict | None:
    for (min_x, min_y, max_x, max_y), feature in features:
        if min_x <= lon <= max_x and min_y <= lat <= max_y:
            if point_in_geometry(lon, lat, feature["geometry"]):
                return feature["properties"]
    return None


def _norm_sigungu(name: str) -> str:
    return "전주시" if name.startswith("전주시") else name


def _sigungu_in_text(text: str) -> str:
    names = ("전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군",
             "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군")
    return next((name for name in names if name in text), "")


def geocode_all(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    key = get_key("KAKAO_REST_KEY")
    cache = _load_cache()
    ok, fail = [], []
    calls = 0
    admins = _admin_features()

    for i, r in enumerate(rows, 1):
        hit = None
        for q, how in variants(r["addr_geo"], r["addr"], r["sigungu"]):
            if q in cache:
                res = cache[q]
            else:
                data = _call(API, {"query": q, "size": 1}, key)
                docs = (data or {}).get("documents") or []
                res = None
                if docs:
                    d = docs[0]
                    # how를 캐시에 함께 저장해야 재실행 시 방법 라벨이 흔들리지 않는다
                    res = {"lat": float(d["y"]), "lon": float(d["x"]),
                           "matched": d.get("address_name") or d.get("place_name", ""),
                           "how": how}
                cache[q] = res
                calls += 1
                time.sleep(0.06)
            if not res and how == "정제주소":
                # 주소 검색 실패 시 기관명 검색. API 종류가 다르므로
                # 주소 캐시와 키를 분리한다.
                keyword_query = f"{r['name']} {r['sigungu']}"
                cache_key = f"keyword::{keyword_query}"
                if cache_key in cache:
                    kw_res = cache[cache_key]
                else:
                    data = _call(KEYWORD_API, {"query": keyword_query, "size": 1}, key)
                    docs = (data or {}).get("documents") or []
                    kw_res = None
                    if docs:
                        d = docs[0]
                        kw_res = {"lat": float(d["y"]), "lon": float(d["x"]),
                                  "matched": d.get("road_address_name") or d.get("address_name")
                                  or d.get("place_name", ""), "how": "장소명검색"}
                    cache[cache_key] = kw_res
                    calls += 1
                    time.sleep(0.06)
                if kw_res:
                    res = kw_res
            if res:
                hit = {**res, "how": res.get("how", how)}
                break
        if hit:
            lat, lon = float(hit["lat"]), float(hit["lon"])
            admin = _admin_at(lon, lat, admins)
            if not admin:
                fail.append({**r, "fail_reason": "outside_jeonbuk_admin_boundary",
                             "candidate_lat": lat, "candidate_lon": lon,
                             "candidate_how": hit["how"], "candidate_matched": hit.get("matched", "")})
                continue
            source_sgg = r["sigungu"]
            coord_sgg = _norm_sigungu(admin["sggnm"])
            matched = hit.get("matched", "")
            matched_sgg = _sigungu_in_text(matched)
            mismatch = bool(source_sgg and coord_sgg != source_sgg)
            matched_mismatch = bool(matched_sgg and matched_sgg != coord_sgg)
            corrected = {**r}
            if mismatch:
                corrected["sigungu_src"] = source_sgg
            quality = "place_name" if hit["how"] == "장소명검색" else "address"
            if mismatch and matched_sgg == source_sgg:
                review = "verified_address_boundary_conflict"
            elif mismatch:
                review = "source_admin_coordinate_conflict"
            elif matched_mismatch:
                review = "matched_address_admin_conflict"
            elif quality == "place_name":
                review = "place_name_polygon_validated"
            else:
                review = "polygon_validated"
            corrected.update({
                "lat": lat, "lon": lon, "geo_how": hit["how"],
                "geo_quality": quality, "geo_matched": matched,
                "geo_matched_sigungu": matched_sgg,
                "coord_admin_code": admin["adm_cd2"],
                "coord_sigungu": coord_sgg,
                "coord_dong": admin["adm_nm"].split()[-1],
                "geo_inside_jeonbuk": "Y",
                "geo_admin_match": "N" if mismatch else "Y",
                "geo_matched_admin_match": "N" if matched_mismatch else "Y",
                "geo_review": review,
            })
            ok.append(corrected)
        else:
            fail.append({**r, "fail_reason": "no_address_or_place_match"})
        if i % 100 == 0:
            print(f"  {i}/{len(rows)} 처리 (성공 {len(ok)}, 실패 {len(fail)}, API 호출 {calls})")

    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return ok, fail


def main() -> int:
    src = DATA_OUT / "points_raw.csv"
    rows = list(csv.DictReader(src.read_text(encoding="utf-8-sig").splitlines()))
    print(f"지오코딩 대상 {len(rows)}건")
    ok, fail = geocode_all(rows)

    fields = ["outlet_id", "type", "name", "addr", "sigungu", "sigungu_src", "detail",
              "finance_open", "finance_status", "status_basis", "lat", "lon", "geo_how",
              "geo_quality", "geo_matched", "geo_matched_sigungu", "coord_admin_code", "coord_sigungu",
              "coord_dong", "geo_inside_jeonbuk", "geo_admin_match", "geo_matched_admin_match",
              "geo_review", "source_correction_id", "source", "source_snapshot"]
    out = DATA_OUT / "points_geocoded.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(ok)
    fail_fields = ["outlet_id", "type", "name", "addr", "sigungu", "finance_status",
                   "fail_reason", "candidate_lat", "candidate_lon", "candidate_how",
                   "candidate_matched", "source_correction_id", "source", "source_snapshot"]
    with (DATA_OUT / "geocode_failed.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=fail_fields, extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(fail)

    print(f"\n성공 {len(ok)}/{len(rows)} ({len(ok)/len(rows)*100:.1f}%) → {out.relative_to(ROOT)}")
    how = {}
    for r in ok:
        how[r["geo_how"]] = how.get(r["geo_how"], 0) + 1
    for k, v in sorted(how.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {v}")
    if fail:
        print(f"실패 {len(fail)}건 → geocode_failed.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
