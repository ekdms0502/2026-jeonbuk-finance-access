"""Collect and geocode the official province-wide senior-center inventory.

The provincial file covers all 14 Jeonbuk municipalities but contains no
coordinates.  Coordinates are reused only when an exact normalized address is
already present in a published public-data output; all other addresses are
looked up with Kakao Local.  Every coordinate is then checked against the SGIS
administrative boundary.  Listing a center is not proof of permission to use
it as a mobile-finance stop.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date

from config import DATA_OUT, DATA_RAW, ROOT, get_key
from geocode import API, KEYWORD_API, _admin_at, _admin_features, _call

SOURCE_PAGE = "https://www.data.go.kr/data/15131430/fileData.do"
DOWNLOAD_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do?"
    "atchFileId=FILE_000000003109249&fileDetailSn=1&insertDataPrcus=N"
)
SOURCE_DATE = "2024-12-31"
EXPECTED_COLUMNS = {"시군명", "경로당명", "주소"}
EXPECTED_ROWS = 6880
EXPECTED_SIGUNGU = {
    "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군",
    "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군",
}

RAW_DIR = DATA_RAW / "venues"
RAW_FILE = RAW_DIR / "jeonbuk_senior_centers_20241231.csv"
CACHE_FILE = RAW_DIR / "jeonbuk_senior_center_geocode_cache.json"
OUTPUT_FILE = DATA_OUT / "venues_jeonbuk.csv"
FAIL_FILE = DATA_OUT / "venues_jeonbuk_geocode_failed.csv"
METADATA_FILE = DATA_OUT / "venues_jeonbuk_metadata.json"


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("전북 경로당 CSV 인코딩을 판별하지 못했습니다.")


def download_source() -> tuple[list[dict[str, str]], str]:
    request = urllib.request.Request(
        DOWNLOAD_URL,
        headers={"User-Agent": "jeonbuk-finance-access/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()
    rows = list(csv.DictReader(decode_csv(content).splitlines()))
    columns = set(rows[0]) if rows else set()
    if columns != EXPECTED_COLUMNS:
        raise RuntimeError(f"전북 경로당 컬럼 변경: {sorted(columns)}")
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"전북 경로당 행수 변경: {len(rows)} != {EXPECTED_ROWS}")
    sigungu = {row["시군명"].strip() for row in rows}
    if sigungu != EXPECTED_SIGUNGU:
        raise RuntimeError(f"전북 경로당 시군 범위 변경: {sorted(sigungu)}")
    if len({tuple(row[field].strip() for field in sorted(EXPECTED_COLUMNS)) for row in rows}) != len(rows):
        raise RuntimeError("전북 경로당 원천에 중복 행이 있습니다.")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with RAW_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["시군명", "경로당명", "주소"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows, hashlib.sha256(content).hexdigest()


def normalize_address(value: str) -> str:
    value = value.replace("전라북도", "").replace("전북특별자치도", "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value)


def province_address(value: str) -> str:
    if value.startswith(("전북특별자치도", "전라북도")):
        return value
    return f"전북특별자치도 {value}"


def source_sigungu(value: str) -> str:
    return "전주시" if value.startswith("전주시") else value


def venue_id(sigungu: str, name: str, address: str) -> str:
    digest = hashlib.sha256(
        f"{sigungu}\0{name}\0{address}".encode()
    ).hexdigest()[:12].upper()
    return f"JSC-{digest}"


def load_cache() -> dict[str, dict | None]:
    if not CACHE_FILE.exists():
        return {}
    return json.loads(CACHE_FILE.read_text(encoding="utf-8"))


def bootstrap_coordinates() -> dict[str, dict]:
    """Reuse only unambiguous exact-address public coordinates."""

    candidates: defaultdict[str, list[dict]] = defaultdict(list)
    sources = [(OUTPUT_FILE, "published_exact_address_reuse")]
    for path, default_method in sources:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                candidates[normalize_address(row.get("addr", ""))].append({
                    "lat": lat,
                    "lon": lon,
                    "matched": row.get("geo_matched") or row.get("addr", ""),
                    "method": row.get("geocode_method") or default_method,
                    "query": row.get("geocode_query") or row.get("addr", ""),
                })
    return {
        address: rows[0]
        for address, rows in candidates.items()
        if address and len({(row["lat"], row["lon"]) for row in rows}) == 1
    }


def kakao_address(query: str, key: str, cache: dict) -> tuple[dict | None, int]:
    cache_key = f"address::{query}"
    if cache_key in cache:
        return cache[cache_key], 0
    data = _call(API, {"query": query, "size": 1}, key)
    documents = (data or {}).get("documents") or []
    result = None
    if documents:
        document = documents[0]
        result = {
            "lat": float(document["y"]),
            "lon": float(document["x"]),
            "matched": document.get("address_name", ""),
        }
    cache[cache_key] = result
    time.sleep(0.04)
    return result, 1


def kakao_keyword(sigungu: str, name: str, key: str, cache: dict) -> tuple[dict | None, int]:
    query = f"전북특별자치도 {sigungu} {name}"
    cache_key = f"keyword::{query}"
    if cache_key in cache:
        return cache[cache_key], 0
    data = _call(KEYWORD_API, {"query": query, "size": 5}, key)
    result = None
    normalized_name = re.sub(r"\s+", "", name)
    for document in (data or {}).get("documents") or []:
        place_name = re.sub(r"\s+", "", document.get("place_name", ""))
        if normalized_name not in place_name:
            continue
        result = {
            "lat": float(document["y"]),
            "lon": float(document["x"]),
            "matched": document.get("road_address_name")
            or document.get("address_name", ""),
        }
        break
    cache[cache_key] = result
    time.sleep(0.04)
    return result, 1


def geocode_rows(rows: list[dict[str, str]]) -> tuple[list[dict], list[dict], int]:
    key = get_key("KAKAO_REST_KEY")
    cache = load_cache()
    bootstrap = bootstrap_coordinates()
    admins = _admin_features()
    output: list[dict] = []
    failed: list[dict] = []
    calls = 0

    for index, source in enumerate(rows, 1):
        sigungu = source["시군명"].strip()
        name = source["경로당명"].strip()
        address = source["주소"].strip()
        result = bootstrap.get(normalize_address(address))
        method = result.get("method", "published_exact_address_reuse") if result else ""
        query = result.get("query", address) if result else ""

        if not result:
            query = province_address(address)
            result, used = kakao_address(query, key, cache)
            calls += used
            method = "kakao_address"

        if not result:
            # Apartment unit/floor text can make an otherwise valid road address fail.
            simplified = re.sub(r"\([^)]*\)", "", province_address(address)).split(",", 1)[0].strip()
            if simplified != query:
                result, used = kakao_address(simplified, key, cache)
                calls += used
                if result:
                    method = "kakao_address_simplified"
                    query = simplified

        if not result:
            result, used = kakao_keyword(sigungu, name, key, cache)
            calls += used
            if result:
                method = "kakao_keyword_name_match"
                query = f"전북특별자치도 {sigungu} {name}"

        row_id = venue_id(sigungu, name, address)
        if not result:
            failed.append({
                "venue_id": row_id,
                "name": name,
                "addr": address,
                "source_sigungu": sigungu,
                "fail_reason": "no_address_or_exact_name_match",
            })
            continue

        lat = float(result["lat"])
        lon = float(result["lon"])
        admin = _admin_at(lon, lat, admins)
        if not admin:
            failed.append({
                "venue_id": row_id,
                "name": name,
                "addr": address,
                "source_sigungu": sigungu,
                "fail_reason": "outside_jeonbuk_admin_boundary",
                "candidate_lat": lat,
                "candidate_lon": lon,
            })
            continue

        coord_sigungu = admin["sggnm"]
        coord_dong = admin["adm_nm"].split()[-1]
        output.append({
            "venue_id": row_id,
            "name": name,
            "venue_type": "경로당",
            "addr": address,
            "source_sigungu": sigungu,
            "coord_admin_code": admin["adm_cd2"],
            "coord_sigungu": coord_sigungu,
            "coord_dong": coord_dong,
            "source_sigungu_match": (
                "Y" if source_sigungu(coord_sigungu) == sigungu else "N"
            ),
            "lat": round(lat, 8),
            "lon": round(lon, 8),
            "geocode_method": method,
            "geocode_query": query,
            "geo_matched": result.get("matched", ""),
            "data_base_date": SOURCE_DATE,
            "use_approval_status": "unverified",
            "time_window_status": "not_provided",
        })
        if index % 100 == 0:
            print(
                f"  {index}/{len(rows)} 좌표화 "
                f"(성공 {len(output)}, 실패 {len(failed)}, API 호출 {calls})",
                flush=True,
            )

    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return output, failed, calls


def write_csv(path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    source_rows, source_sha256 = download_source()
    output, failed, calls = geocode_rows(source_rows)
    output.sort(key=lambda row: (row["coord_admin_code"], row["name"], row["venue_id"]))
    failed.sort(key=lambda row: (row["source_sigungu"], row["name"], row["venue_id"]))

    output_fields = [
        "venue_id", "name", "venue_type", "addr", "source_sigungu",
        "coord_admin_code", "coord_sigungu", "coord_dong", "source_sigungu_match",
        "lat", "lon", "geocode_method", "geocode_query", "geo_matched",
        "data_base_date", "use_approval_status", "time_window_status",
    ]
    fail_fields = [
        "venue_id", "name", "addr", "source_sigungu", "fail_reason",
        "candidate_lat", "candidate_lon",
    ]
    write_csv(OUTPUT_FILE, output, output_fields)
    write_csv(FAIL_FILE, failed, fail_fields)

    match_counts = Counter(row["source_sigungu_match"] for row in output)
    metadata = {
        "source_page": SOURCE_PAGE,
        "download_url": DOWNLOAD_URL,
        "provider": "전북특별자치도",
        "source_data_base_date": SOURCE_DATE,
        "collected_date": date.today().isoformat(),
        "source_sha256": source_sha256,
        "source_columns": ["시군명", "경로당명", "주소"],
        "source_contains_phone": False,
        "source_rows": len(source_rows),
        "source_sigungu_count": len({row["시군명"].strip() for row in source_rows}),
        "geocoded_rows": len(output),
        "failed_rows": len(failed),
        "source_sigungu_match_counts": dict(match_counts),
        "coordinate_source": (
            "exact-address public coordinate reuse or Kakao Local, then SGIS boundary audit"
        ),
        "license": "공공데이터포털 이용허락범위 제한 없음",
        "operational_guard": (
            "listed senior center is a candidate only; use approval and time window are unverified"
        ),
    }
    METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"전북 경로당 {len(output)}/{len(source_rows)} 좌표화 "
        f"(14개 시군, 시군 일치 {match_counts.get('Y', 0)}, "
        f"검토 {match_counts.get('N', 0)}, 실패 {len(failed)}, API 호출 {calls})"
    )
    print(f"→ {OUTPUT_FILE.relative_to(ROOT)}")
    return 0 if output and len({row["source_sigungu"] for row in output}) == 14 else 1


if __name__ == "__main__":
    sys.exit(main())
