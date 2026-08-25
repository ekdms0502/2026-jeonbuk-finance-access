#!/usr/bin/env bash
# GitHub 클론만으로 가능한 공유 데이터 검증
set -uo pipefail
cd "$(dirname "$0")"
FAIL=0

echo "== 1. Python 문법 =="
if python3 -m compileall -q src; then
  echo "  OK  src/*.py 컴파일"
else
  echo "  FAIL Python 문법 오류"
  FAIL=1
fi

echo "== 2. 경로 엔진 단위 테스트 =="
if PYTHONPATH=src python3 -m unittest discover -s tests -v; then
  echo "  OK  경로 엔진 테스트"
else
  echo "  FAIL 경로 엔진 테스트"
  FAIL=1
fi

echo "== 3. 전북 분석·시나리오 산출물 재생성 =="
if PYTHONPATH=src python3 src/build_typology.py && \
   PYTHONPATH=src python3 src/build_jeonbuk_route_scenario.py --reuse-matrix && \
   PYTHONPATH=src python3 src/build_scenario_evidence.py && \
   PYTHONPATH=src python3 src/build_dashboard_data.py && \
   node --check docs/demo-jeonbuk/app.js && \
   node --check docs/demo-jeonbuk/scenario-engine.js && \
   node --test tests/test_dashboard_engine.js; then
  echo "  OK  전북 243개 행정동 유형·경로·민감도와 브라우저 엔진"
else
  echo "  FAIL 전북 분석·시나리오 산출물 또는 브라우저 엔진"
  FAIL=1
fi

echo "== 4. 상세 무결성 재계산 =="
if PYTHONPATH=src python3 src/validate_outputs.py; then
  echo "  OK  상세 검증 재계산"
else
  echo "  FAIL 상세 검증"
  FAIL=1
fi

echo "== 5. 공유 데이터 =="
PYTHONPATH=src python3 - <<'PY' || FAIL=1
import csv
import json
from pathlib import Path

root = Path("data/processed")
expected_rows = {
    "points_raw.csv": 681,
    "points_geocoded.csv": 681,
    "geocode_failed.csv": 0,
    "source_corrections.csv": 1,
    "outlets_validated.csv": 681,
    "coordinate_clusters_5m.csv": 658,
    "access_jeonbuk.csv": 243,
    "access_road.csv": 243,
    "access_typology.csv": 243,
    "ecos_jeonbuk_loans_202508_202605.csv": 10,
    "venues_jeonbuk.csv": 6856,
    "venues_jeonbuk_geocode_failed.csv": 24,
}

for name, expected in expected_rows.items():
    path = root / name
    if not path.is_file():
        raise SystemExit(f"FAIL {path} 없음")
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    if len(rows) != expected:
        raise SystemExit(f"FAIL {path}: {len(rows)}행, 예상 {expected}행")
    print(f"  OK  {name}: {len(rows):,}행")

for name in ("jeongeup_demo.json", "jeongeup_geom.json",
             "jeongeup_post.json", "jeongeup_snapshot_metadata.json", "roadnet_metadata.json",
             "typology_evaluation.json", "venues_jeonbuk_metadata.json",
             "jeonbuk_route_scenario.json", "scenario_evidence.json",
             "ecos_jeonbuk_loans_metadata.json"):
    path = root / name
    json.loads(path.read_text(encoding="utf-8"))
    print(f"  OK  {name}: JSON 파싱")

audit_path = root / "geocode_reverse_audit.csv"
audit = list(csv.DictReader(audit_path.read_text(encoding="utf-8-sig").splitlines()))
if not audit or any(not row["reverse_address_kakao"] for row in audit):
    raise SystemExit("FAIL geocode_reverse_audit.csv: 표본 없음 또는 역주소 공란")
print(f"  OK  geocode_reverse_audit.csv: {len(audit)}행")

for name in ("index.html", "methodology.html", "app.js", "data.js",
             "map-data.js", "scenario-engine.js"):
    path = Path("docs/demo-jeonbuk") / name
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"FAIL {path} 없음 또는 공란")
    print(f"  OK  {path}: {path.stat().st_size:,} bytes")
PY

echo
[ "$FAIL" -eq 0 ] && echo "PASS (offline)" || echo "FAIL ($FAIL)"
exit "$FAIL"
