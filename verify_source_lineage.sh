#!/usr/bin/env bash
# 원천 스냅샷 보유 환경에서만 실행하는 해시·행정경계·수집계보 검증
set -uo pipefail
cd "$(dirname "$0")"

required=(
  data/raw/hjd2026.geojson
  data/raw/mois_haengjeongdong_age_sex_20260630.csv
  data/raw/post_offices_utf8.csv
  data/raw/points/kfb_jeonbuk_full.csv
  data/raw/points/cu_jeonbuk.csv
  data/raw/points/kfcc_mg_jeonbuk.csv
  data/raw/points/kfcc_collection_metadata.json
  data/raw/south-korea-latest.osm.pbf
  data/raw/venues/jeonbuk_senior_centers_20241231.csv
)

missing=()
for path in "${required[@]}"; do
  [ -s "$path" ] || missing+=("$path")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "FAIL 원천 계보 검증에 필요한 파일이 없습니다:"
  printf '  - %s\n' "${missing[@]}"
  exit 1
fi

PYTHONPATH=src python3 src/validate_outputs.py --raw-lineage
