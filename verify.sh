#!/usr/bin/env bash
# 프로젝트 최소 검증: 키 설정 → ECOS 연결 → 원본 데이터 존재 확인
set -uo pipefail
cd "$(dirname "$0")"
FAIL=0

echo "== 1. 비밀정보 보호 =="
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git check-ignore -q .env; then echo "  OK  .env가 gitignore에 잡힘"
  else echo "  FAIL .env가 추적될 수 있음!"; FAIL=1; fi
else
  grep -q '^\.env$' .gitignore && echo "  OK  .gitignore에 .env 등록 (git 미초기화)" || { echo "  FAIL"; FAIL=1; }
fi
grep -qE '^[A-Z_]+=PASTE_YOUR_KEY_HERE' .env 2>/dev/null && echo "  WARN 미설정 키가 있습니다"
python3 - <<'PY' 2>/dev/null
import re,pathlib
bad=[l.split('=')[0] for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines()
     if re.match(r'^[A-Z_]+=', l) and 0 < len(l.split('=',1)[1].strip()) < 15]
print("  WARN 값이 너무 짧은 키: "+", ".join(bad) if bad else "  OK  키 형식 정상")
PY

echo "== 2. 원본 데이터 =="
for f in data/raw/hjd2026.geojson data/raw/mois_haengjeongdong_age_sex_20260630.csv data/raw/post_offices_utf8.csv; do
  [ -s "$f" ] && echo "  OK  $f ($(du -h "$f" | cut -f1))" || { echo "  FAIL $f 없음"; FAIL=1; }
done

echo "== 3. 외부 API 연결 =="
PYTHONPATH=src python3 src/ecos.py 2>&1 | tail -3 | sed 's/^/  ECOS  /' || FAIL=1
PYTHONPATH=src python3 -c "
import sys; sys.path.insert(0,'src')
from datagokr import total_count, VILLAGE_HALL_API, DataGoKrError
from config import get_key
try:
    n=total_count(VILLAGE_HALL_API); print(f'OK 경로당 API 총 {n:,}건')
except DataGoKrError as e: print(f'FAIL {e}'); sys.exit(1)
except RuntimeError as e: print(f'SKIP {e}')
" 2>&1 | sed 's/^/  공공데이터  /' || FAIL=1
PYTHONPATH=src python3 -c "
import sys,json,urllib.request,urllib.parse; sys.path.insert(0,'src')
from config import get_key
k=get_key('KAKAO_REST_KEY')
q=urllib.parse.urlencode({'query':'전북특별자치도 전주시 팔달로 159'})
r=urllib.request.Request(f'https://dapi.kakao.com/v2/local/search/address.json?{q}',headers={'Authorization':f'KakaoAK {k}'})
d=json.load(urllib.request.urlopen(r,timeout=15))
print('OK 지오코딩' if d.get('documents') else 'FAIL 결과없음')
" 2>&1 | sed 's/^/  카카오    /' || FAIL=1

echo
[ $FAIL -eq 0 ] && echo "PASS" || echo "FAIL ($FAIL)"
exit $FAIL
