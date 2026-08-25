"""Deterministic Kakao reverse-geocode sample for outlet coordinate QA.

The independent SGIS polygon containment check covers all rows.  This script
adds a human-readable reverse-address sample: one outlet per available
(type, sigungu) group, every place-name geocode, and every point outside the
old mainland bbox.  API credentials are read but never printed.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from config import ROOT, DATA_OUT, get_key

API = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
CACHE = DATA_OUT / "reverse_geocode_cache.json"
SIGUNGU = ("전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군",
           "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군")


def sigungu_in(text: str) -> str:
    return next((name for name in SIGUNGU if name in text), "")


def call_reverse(lon: float, lat: float, key: str) -> dict | None:
    query = urllib.parse.urlencode({"x": lon, "y": lat, "input_coord": "WGS84"})
    request = urllib.request.Request(f"{API}?{query}", headers={"Authorization": f"KakaoAK {key}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                docs = json.load(response).get("documents") or []
            if not docs:
                return None
            doc = docs[0]
            road = doc.get("road_address") or {}
            parcel = doc.get("address") or {}
            return {
                "reverse_address": road.get("address_name") or parcel.get("address_name") or "",
                "reverse_sigungu": road.get("region_2depth_name") or parcel.get("region_2depth_name") or "",
            }
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


def main() -> int:
    rows = list(csv.DictReader(
        (DATA_OUT / "outlets_validated.csv").read_text(encoding="utf-8-sig").splitlines()
    ))
    reasons: dict[str, set[str]] = defaultdict(set)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["type"], row["coord_sigungu"])].append(row)
        if row["geo_quality"] == "place_name":
            reasons[row["outlet_id"]].add("place_name_geocode")
        if row["geo_admin_match"] == "N" or row["geo_matched_admin_match"] == "N":
            reasons[row["outlet_id"]].add("admin_conflict")
        lat, lon = float(row["lat"]), float(row["lon"])
        if not (35.0 <= lat <= 36.2 and 126.3 <= lon <= 127.9):
            reasons[row["outlet_id"]].add("outside_old_bbox")
    for group_rows in grouped.values():
        chosen = min(group_rows, key=lambda row: row["outlet_id"])
        reasons[chosen["outlet_id"]].add("stratified_type_sigungu")

    selected = [row for row in rows if row["outlet_id"] in reasons]
    selected.sort(key=lambda row: row["outlet_id"])
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    key = get_key("KAKAO_REST_KEY")
    audit = []
    calls = 0
    for row in selected:
        cache_key = f"{float(row['lon']):.7f},{float(row['lat']):.7f}"
        if cache_key in cache:
            reverse = cache[cache_key]
        else:
            reverse = call_reverse(float(row["lon"]), float(row["lat"]), key)
            cache[cache_key] = reverse
            calls += 1
            time.sleep(0.06)
        reverse = reverse or {"reverse_address": "", "reverse_sigungu": ""}
        reverse_sgg = sigungu_in(reverse["reverse_sigungu"] or reverse["reverse_address"])
        status = "PASS" if reverse_sgg == row["coord_sigungu"] else "REVIEW"
        audit.append({
            "outlet_id": row["outlet_id"], "type": row["type"], "name": row["name"],
            "source_addr": row["addr"], "lat": row["lat"], "lon": row["lon"],
            "source_correction_id": row.get("source_correction_id", ""),
            "coord_sigungu_sgis": row["coord_sigungu"],
            "reverse_address_kakao": reverse["reverse_address"],
            "reverse_sigungu_kakao": reverse_sgg,
            "audit_status": status,
            "sample_reason": " | ".join(sorted(reasons[row["outlet_id"]])),
            "audit_date": "2026-08-11",
        })
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    out = DATA_OUT / "geocode_reverse_audit.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=list(audit[0].keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(audit)
    counts = Counter(row["audit_status"] for row in audit)
    print(f"역지오코딩 표본 {len(audit)}건: {dict(counts)} (API 호출 {calls})")
    print(f"출력: {out.relative_to(ROOT)}")
    return 1 if any(not row["reverse_address_kakao"] for row in audit) else 0


if __name__ == "__main__":
    sys.exit(main())
