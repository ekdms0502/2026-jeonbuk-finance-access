# 전북 금융 사각지대 진단과 찾아가는 은행 최적 동선 설계 — 코드·분석파일

팀명: **금방**(금융 방방곡곡) · 대표자: 정다은

2026 제4회 전북 청년 AI·빅데이터 경진대회 · **현안 해결 구현 분야** 제출물.

전북 14개 시군 243개 행정동의 금융 접근성을 공개 데이터로 진단하고, 차량 수·운영일·
방문 상한이 제한된 조건에서 찾아가는 금융 서비스의 시군별 순회 거점과 방문 순서를
제안한다.

- 대회 필수 데이터: 한국은행 ECOS `141Y003` 예금은행 지역별 대출금(말잔)

---

## 1. 빠른 실행 (5분)

원본 대용량 데이터나 API 키 없이, 이 압축파일만으로 전체 검증이 돌아간다.

```bash
cd 금방_전북금융사각지대진단과찾아가는은행최적동선설계_코드분석파일
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m pip install -r requirements.txt
bash verify_offline.sh             # 문법·테스트·산출물 재생성·무결성 검증
```

마지막 줄에 `PASS (offline)` 이 찍히면 정상이다.

대시보드는 서버 없이 파일을 그대로 열면 된다.

```bash
open docs/demo-jeonbuk/index.html          # Windows: start docs\demo-jeonbuk\index.html
```

`verify_offline.sh`가 하는 일은 다섯 단계다.

| 단계 | 내용 |
|---|---|
| 1 | `src/*.py` 전체 컴파일 |
| 2 | 경로 엔진 단위 테스트 (`tests/`) |
| 3 | 유형·순회·민감도·대시보드 산출물 재생성 + 브라우저 엔진 테스트 |
| 4 | 접점 좌표·경계·조인 무결성 재계산 (`src/validate_outputs.py`) |
| 5 | 가공 데이터 행 수와 JSON 파싱 확인 |

## 2. 실행 환경

| 항목 | 요구 |
|---|---|
| 운영체제 | macOS / Linux / Windows(WSL 권장) |
| Python | 3.11 이상 (개발·검증: 3.14.6) |
| Node.js | 20 이상 — 브라우저 시나리오 엔진 테스트용 (개발·검증: 26.4.0) |
| 브라우저 | Chrome·Safari·Edge 최신 (대시보드 열람) |
| 네트워크 | **불필요** — 위 검증은 전부 오프라인 |

자세한 내용은 [`docs/실행환경설명서.md`](docs/실행환경설명서.md) (PDF 판본: `docs/실행환경설명서.pdf`)를 따른다.

## 3. 필요 라이브러리

`requirements.txt` 세 개가 전부다. 나머지는 Python 표준 라이브러리만 쓴다.

```
osmium==4.3.1     OSM PBF 파싱 (원본 도로망 재구축 시에만 필요)
numpy==2.4.6      수치 연산
scipy==1.17.1     Ward 계층 군집
```

Node.js는 별도 패키지 설치 없이 내장 `node:test`만 쓴다.

## 4. 폴더 구성

```
금방_전북금융사각지대진단과찾아가는은행최적동선설계_코드분석파일/
├── README.md                  이 문서 — 실행 설명서
├── requirements.txt           필요 라이브러리
├── verify_offline.sh          제출 검증 (키·원본 없이 실행)
├── verify.sh                  API 키 포함 최소 검증
├── verify_source_lineage.sh   원본 보유 환경 전용 계보 검증
├── src/                       수집·정제·분석·경로·시각화 코드 (21개 모듈)
├── config/                    운영 가정·입력 범위 설정
├── tests/                     경로 엔진·유형화·대시보드 엔진 테스트
├── data/
│   ├── processed/             코드가 참조하는 실제 가공 데이터 (전량 포함)
│   └── source_manifest.json   원천별 URL·기준일·수집일·라이선스·SHA-256
├── data_sample/               가공 데이터 상위 20행 미리보기 + 데이터 설명서
├── result/
│   ├── reports/               분석 결과 리포트 4종 (Markdown)
│   └── outputs/               최종 산출 CSV·JSON 사본
└── docs/
    ├── 실행환경설명서.md
    ├── 제출_체크리스트.md
    ├── AI_USAGE.md            AI·바이브 코딩 활용 범위
    ├── THIRD_PARTY_NOTICES.md 오픈소스 출처·라이선스
    ├── DATASETS.md            데이터 목록·출처·재현 조건
    └── demo-jeonbuk/          대시보드·지도·방법론 화면
```

Jupyter 노트북은 두지 않았다. 수집부터 시각화까지 전 과정을 재실행 가능한
스크립트로 구성했고, `verify_offline.sh` 한 줄이 그 파이프라인을 그대로 돌린다.

## 5. 데이터 경로와 파일명

### 코드가 읽는 경로

모든 스크립트는 저장소 루트 기준 상대경로만 쓴다. 절대경로·사용자 홈 경로는 없다.

| 경로 | 내용 | 포함 여부 |
|---|---|---|
| `data/processed/` | 가공·검증 완료 데이터 28개 | **포함** — 그대로 실행 가능 |
| `data/raw/` | 원본 공개 데이터 | **미포함** — 용량(약 370MB)·재배포 조건 |
| `data/source_manifest.json` | 원천 URL·기준일·수집일·라이선스·SHA-256 | 포함 |
| `docs/demo-jeonbuk/data.js`, `map-data.js` | 대시보드 입력 번들 (재생성됨) | 포함 |

`data/raw/`가 없어도 `verify_offline.sh`는 전부 통과한다. 원본이 필요한 단계
(OSM 도로망 재구축, 원천 SHA-256 대조)는 `verify_source_lineage.sh`로 분리했다.

### 주요 파일

| 파일 | 행 수 | 내용 |
|---|---:|---|
| `data/processed/points_raw.csv` | 681 | 은행·우체국·신협·새마을금고 접점 원본 |
| `data/processed/outlets_validated.csv` | 681 | 좌표·경계 검증 완료 접점 |
| `data/processed/access_jeonbuk.csv` | 243 | 행정동별 직선거리 접근성 |
| `data/processed/access_road.csv` | 243 | 행정동별 OSM 도로거리 접근성 |
| `data/processed/access_typology.csv` | 243 | 취약유형 라벨 |
| `data/processed/venues_jeonbuk.csv` | 6,856 | 전북 14개 시군 공식 경로당 좌표화 |
| `data/processed/ecos_jeonbuk_loans_202508_202605.csv` | 10 | ECOS 전북 원화대출금 공개 샘플 |
| `data/processed/jeonbuk_route_scenario.json` | — | 차량 3대·5일 순회 배정 결과 |
| `data/processed/scenario_evidence.json` | — | 임계값·속도·서비스시간 민감도 감사 |

전체 원천 목록·수집 방식·라이선스는 [`docs/DATASETS.md`](docs/DATASETS.md),
기계판독 원장은 `data/source_manifest.json`을 따른다.

## 6. 결과물

`result/reports/`의 네 문서가 분석 결과의 본문이다.

| 문서 | 내용 |
|---|---|
| `quality_report.md` | 데이터 품질·검증 항목과 남은 한계 |
| `coverage_by_sigungu.md` | 시군별 접근성 커버리지 |
| `typology_evaluation.md` | 군집 후보 `k=2..5` 채택·기각 근거 |
| `scenario_evidence.md` | 순회 시나리오 민감도 감사 |

핵심 수치는 다음과 같다.

- 전북 243개 행정동 중 도로거리 3km 초과 **71개**, 이 중 품질 게이트 통과 **69개**를 경로 대상으로 사용
- 차량 3대·5일 기본안에서 **57/69곳** 방문. 최소안 1대 20곳, 확대안 5대 69곳
- 취약유형은 `k=2` 채택 (실루엣 0.686, 재표집 ARI 중앙 1.000, `log1p` 대안 ARI 0.779)

`57/69`는 **방문 대상 행정동 대표점 수**이지 주민 커버리지나 접근성 개선 인구가 아니다.
거리 결과는 행정동 대표점 하나에서 계산한 접근성 프록시이며, 주민 개인의 실제
이동거리로 해석하면 안 된다. 차고지·장소 사용승인·시간창이 확정되지 않아
대시보드는 `operational_ready=false`를 그대로 표시한다.

## 7. AI 활용 범위

[`docs/AI_USAGE.md`](docs/AI_USAGE.md)에 전문을 두었다. 요약하면,

- **탐색형 분석모델**: SciPy Ward 계층 군집으로 농촌 읍·면 155개의 취약유형을 탐색.
  실루엣·재표집 ARI·최소 군집 크기·전처리 민감도 게이트를 모두 통과한 후보만 공개한다.
- **생성형 AI 개발 보조**: Claude·Codex를 코드 초안, 검증 스크립트, 문서 정리,
  방법론 조사 보조에 사용했다. 줄 단위 생성 이력을 남기지 않았으므로 **저장소의 코드와
  문서 전체를 AI 보조 범위로 보수적으로 간주**한다.
- **쓰지 않은 범위**: 생성형 AI를 산출물 기능에 넣지 않았고, 순회 경로 계산은 동적계획법
  기반 운영최적화이지 AI 모델이 아니다. 개인 위험도 산출·금융상품 추천은 하지 않는다.

## 8. 오픈소스·외부 데이터 출처

[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md)에 라이선스 전문 위치를 정리했다.
주요 항목은 OpenStreetMap(ODbL), SGIS 기반 행정동 경계 재배포본(CC BY 4.0),
Pretendard 글꼴(SIL OFL 1.1), NumPy·SciPy·PyOsmium(BSD/LGPL)이다.

## 9. 제출 기준 대응

`docs/제출_체크리스트.md`에 「코드·분석파일 제출 기준」의 확인 항목별 근거 파일을 정리했다.
