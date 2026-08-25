# data_sample — 데이터 미리보기와 설명

## 이 폴더에 있는 것

- `*.sample.csv` — `data/processed/`의 각 가공 CSV 상위 20행 미리보기. 컬럼 구조를
  빠르게 확인하는 용도다.
- `source_manifest.json` — 원천별 URL·기준일·수집일·라이선스·SHA-256 원장.
- `데이터_설명서.md` — 데이터 목록·출처·정제 규칙·재현 조건 전문.

## 실제 분석에 쓰이는 데이터는 어디에 있나

코드가 읽는 경로는 `data/processed/`이고, **가공 데이터는 전량 포함**되어 있다.
따라서 이 폴더의 미리보기 파일을 쓰지 않아도 `bash verify_offline.sh`가 그대로 돌아간다.

`data/raw/`의 원본 공개 데이터(약 370MB)만 용량·재배포 조건 때문에 제외했다.
재다운로드 방법은 `데이터_설명서.md`와 `source_manifest.json`에 있다.
