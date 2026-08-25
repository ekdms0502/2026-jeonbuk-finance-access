# 데이터 목록·출처·재현 조건

제출용 수치의 기준 문서다. **접점**은 공개 목록의 서로 다른 점포 레코드를 뜻하며, 좌표가 가깝다는 이유로 삭제하지 않는다.

산출물 갱신일은 2026-08-13이다. 원천별 기준일·수집일은 아래 표와 매니페스트에 따르며,
우체국 위치 API는 활용승인 전이므로 호출하지 않고 2026-08-10 공개 CSV 스냅샷을 사용했다.

## 1. 대회 필수 데이터

| 항목 | 내용 |
|---|---|
| 데이터명 | 예금은행 지역별 대출금(말잔) 외 지역 여수신 통계 |
| 제공기관 | 한국은행 ECOS |
| 통계표 | `141Y003`(대출금), `141Y002`(수신) |
| 항목 | `200000` 원화대출금 / `Q00` 전북—순서는 `(계정항목, 지역)` |
| 주기·범위 | 월간, 199512~202605 |
| 수집일 | 최초 확인 2026-08-10; 제출용 공개 스냅샷 재수집 2026-08-13 |
| 확인값 | 2026-05 전북 원화대출금 38,420.9십억 원 |

ECOS는 대회 필수 데이터 요건에 사용하지만 접점 위치나 거리 계산의 원천은 아니다. 공식
`sample` 키로 재수집 가능한 최근 10개월은 `data/processed/ecos_jeonbuk_loans_202508_202605.csv`와
메타데이터에 보존했다. ECOS 지역별 점포수 통계는 확인되지 않았다.

## 2. 원천 데이터

| # | 데이터 | 제공기관·경로 | 현재 스냅샷 | 파일 | 수집일 |
|---:|---|---|---|---|---|
| 1 | 행정동 경계 | 통계청 SGIS 기반 vuski/admdongkor CC BY 4.0 재배포본 | 전국 3,558 / 전북 243, WGS84, 2026-07-01 기준 | `data/raw/hjd2026.geojson` | 2026-08-10 |
| 2 | 성별·연령별 주민등록인구 | 행정안전부·공공데이터포털 | CP949 CSV, 230컬럼, 2026-06-30 기준 | `data/raw/mois_haengjeongdong_age_sex_20260630.csv` | 2026-08-10 |
| 3 | 우체국 정보 | 우정사업본부·공공데이터포털 공개 CSV | 전국 3,264 / 전북 주소 243 | `data/raw/post_offices_utf8.csv` | 2026-08-10 |
| 4 | 은행 점포 | 전국은행연합회 공시 열람 집계 | 전북 175, 2025.12말 기준 | `data/raw/points/kfb_jeonbuk_full.csv` (비공개 보관) | 2026-08-10 |
| 5 | 신협 점포 | 신협중앙회 점포 조회 | 전북 128 | `data/raw/points/cu_jeonbuk.csv` (비공개 보관) | 2026-08-10 |
| 6 | 새마을금고 점포 | 새마을금고중앙회 `map/list.do` | 전북 141; 14개 시군별 `endElement`=실제 행수 | `data/raw/points/kfcc_mg_jeonbuk.csv` (비공개 보관), `data/raw/points/kfcc_collection_metadata.json` | 2026-08-11 |
| 7 | 도로망 | OpenStreetMap Geofabrik south-korea PBF | MD5 `9269d6a6df9c7053fe3aeb31fcf41da2` | `data/raw/south-korea-latest.osm.pbf` | 2026-08-11 |
| 8 | 주소·장소명 좌표 | 카카오 로컬 API | 681건; 주소 679, 장소명 2 | `data/processed/geocode_cache.json` (비공개 보관) | 2026-08-11 |
| 9 | 전북 시군 경로당 현황 | [공공데이터포털](https://www.data.go.kr/data/15131430/fileData.do) | 14개 시군 6,880건, 시군명·경로당명·주소, 좌표·전화번호 없음, 2024-12-31 기준 | `data/raw/venues/jeonbuk_senior_centers_20241231.csv` | 2026-08-12 |

정확한 원천 페이지·다운로드 URL, 기준일과 수집일의 구분, 수집 방식·질의, 라이선스·이용조건,
로컬 원본 SHA-256·바이트 수는 `data/source_manifest.json`이 기계판독 가능한 진실원천이다.
로그인·상태 의존 조회는 조회 화면과 필터를 기록하고 원본 스냅샷은 재배포하지 않는다.
재배포 제한 스냅샷과 카카오 응답 캐시는 팀이 비공개 보관하며(공개 저장소 미포함),
SHA-256을 매니페스트에 남겨 계보 검증 시 대조한다.

은행 175건은 현재 파일의 레코드 수다. 한국은행 2024년말 178개와는 분류·기준일이 달라 `98.3% 완전성`의 분모로 사용하지 않는다. 전수성을 주장하려면 전국은행연합회의 공식 전체 내보내기 또는 수집 로그가 추가로 필요하다.

## 3. 접점 정의·정제

| 유형 | 원천 | 제외 | 점포 레코드 |
|---|---:|---:|---:|
| 우체국 | 243 | 군사우편 1 | 242 |
| 은행 | 175 | 0 | 175 |
| 신협 | 128 | 0 | 128 |
| 새마을금고 | 141 | 직장금고 5 | 136 |
| **합계** | **687** | **6** | **681** |

- 군사우편 1건과 직장 임직원 전용으로 분류된 직장금고 5건만 제외했다.
- `(type, name, addr)` 완전 일치 중복은 0건이다.
- 은행연합회 원천의 `NH농협은행 전북혁신도시지점` 주소 `전주시 안전로 163`은 [NH농협은행 공식 채용공고](https://with.nonghyup.com/jbnf/jbnfDtl.do?jbnfSqno=76719)의 `완주군 이서면 안전로 163`과 불일치해 `CORR-001`로 정정했다. 원천값·정정값·근거 URL은 `data/processed/source_corrections.csv`에 보존한다.
- 25m 좌표 중복 제거는 폐기했다. 가까운 서로 다른 지점을 지우기 때문이다.
- 5m 이내 좌표 연결성분을 탐색용 ID로만 부여했다. 681개 점포는 658개 군집을 이루며, 2개 이상 점포 군집 20개, 이종 기관 군집 10개다. 이는 확인된 건물 수가 아니다.

### 금융 상태 프록시

| `finance_status` | 건수 | 해석 |
|---|---:|---|
| `listed_assumed_open` | 439 | 은행·신협·새마을금고 공개 목록 등재; 실시간 영업 확인 아님 |
| `open_reported` | 204 | 우체국 원천에 금융영업시간 기재 |
| `closed_reported` | 35 | 우체국 원천 금융영업시간이 `미운영` |
| `suspended_unverified` | 3 | 원천 기관명에 재건축·업무중지 문구; 현재 상태는 재확인 필요 |

거리 분석은 `finance_open=Y` 643건을 접점 프록시로 사용한다. `Y`는 실시간 문 열림을 보증하지 않는다.

## 4. 지오코딩 검증

- 성공 681/681: 주소 검색 679, 기관명 장소검색 2.
- 시군·읍면 중심점 폴백은 0건이며 성공 방법에서 제거했다.
- 681건 모두 SGIS 전북 243개 행정동 폴리곤 안에 있다.
- 기존 편의 bbox(위도 35.0~36.2, 경도 126.3~127.9) 밖 2건은 부안위도우체국·군산어청도우체국으로 SGIS 행정경계 안의 정상 섬 좌표다.
- `NH농협은행 전북혁신도시지점`은 공식 주소와 카카오 반환 주소가 완주군이나 SGIS 행정동 경계는 전주시로 판정해 `verified_address_boundary_conflict`로 표시했다. 접점 좌표는 공식 주소로 검색한 값을 사용하고 시군 필드는 완주군을 유지한다.
- `src/audit_geocodes.py`가 유형×시군 층화 표본, 장소명 검색 2건, 행정경계 충돌 1건, bbox 밖 2건을 역지오코딩으로 재확인한다. 같은 카카오 제공자를 쓰므로 독립 지오코더 검증은 아니다.

## 5. 가공 산출물

| 파일 | 행수 | 용도 |
|---|---:|---|
| `data/processed/points_raw.csv` | 681 | 원천 점포 통합·상태 프록시 |
| `data/processed/points_geocoded.csv` | 681 | 좌표+SGIS 행정경계 검증 |
| `data/processed/geocode_failed.csv` | 0 | 좌표 미확정; 헤더는 항상 존재 |
| `data/processed/source_corrections.csv` | 1 | 원천값·정정값·공식 근거 URL 장부 |
| `data/processed/outlets_validated.csv` | 681 | 접점 ID·상태·좌표 군집 포함 마스터 |
| `data/processed/coordinate_clusters_5m.csv` | 658 | 5m 좌표 연결성분; 중복 제거용 아님 |
| `data/processed/geocode_reverse_audit.csv` | 60 | 층화 표본 역지오코딩; PASS 59, REVIEW 1 |
| `data/processed/access_jeonbuk.csv` | 243 | 행정동 내부 대표점 직선거리 프록시 |
| `data/processed/access_road.csv` | 243 | 일방통행 반영 OSM 도로거리 프록시 |
| `data/processed/access_typology.csv` | 243 | 농촌 비교집단 탐색형 군집과 규칙형 안전장치 |
| `data/processed/typology_evaluation.json` | 1 | 군집 후보·안정성·채택 게이트·대표 읍면 |
| `data/processed/ecos_jeonbuk_loans_202508_202605.csv` | 10 | ECOS 공식 공개 샘플; 대회 필수 데이터 맥락, 모델 입력 아님 |
| `data/processed/venues_jeonbuk.csv` | 6,856 | 전북 공식 경로당 좌표화·SGIS 행정경계 감사 통과 |
| `data/processed/venues_jeonbuk_geocode_failed.csv` | 24 | 주소·시군 경계를 확정하지 못한 행 |
| `data/processed/venues_jeonbuk_metadata.json` | 1 | 6,880건 원천 해시·좌표 성공률·14개 시군 범위 |
| `data/processed/jeonbuk_route_scenario.json` | 1 | 14개 시군 대상·후보·방향성 행렬·경로일 배정·순회 결과 |
| `data/processed/scenario_evidence.json` | 1 | 임계값·방문상한·속도·서비스시간·점포상태·후보 프록시 감사 |
| `docs/demo-jeonbuk/data.js` | 243 + 경로행렬 | 전북 지도·민감도 비교용 축약 번들; 가공 산출물에서 재생성 |
| `docs/demo-jeonbuk/map-data.js` | 경계 243 + 경로구간 434 | SGIS 경계·OSM 주요도로·방향성 최단경로 화면 번들 |
| `data/processed/roadnet_metadata.json` | 1 | PBF·bbox·그래프·라우팅 재현 조건 |
| `data/processed/jeongeup_demo.json` | 행정동 23 | 현재 마스터에서 재생성한 정읍 스냅샷 |
| `data/processed/jeongeup_post.json` | 19 | 정읍 우체국; 타 지역·면중심 폴백 없음 |
| `data/processed/validation_checks.csv` | 실행 시 기록 | 오프라인 무결성 검사 |

`access_jeonbuk.csv`의 `nearest_km`는 `finance_open=Y` 접점까지의 직선거리다. `population_exposure_valid=N`은 거리 임계치를 행정동 전체 인구에 적용하면 안 된다는 뜻이다.

`access_road.csv`의 기본식은 `road_km = admin_snap_km + network_km + outlet_snap_km`다. `road_distance_primary=Y` 239개는 정확한 최근접 OSM 노드를 사용했다. 4개는 최근접 노드가 일방통행·분리도로망에서 도달 불가라 2km 안의 가장 가까운 도달 가능 노드를 사용했고 `road_distance_primary=N`으로 플래그했다.

`access_typology.csv`는 전북 전체에 군집을 강제하지 않는다. 읍·면이면서
`road_distance_primary=Y`인 155개만 Ward 계층 군집 적합에 사용하고, 도시 동 84개와 도로거리
폴백 읍·면 4개는 모델 라벨을 비워 둔다. 모델 채택 여부와 군집별 안정성은
`typology_evaluation.json`을 따른다. 규칙형 유형은 원지표 비교용이며 주민별 금융소외 판정이 아니다.
유형 입력의 `road_km`는 OSM 방향성 도로거리지만 `cnt_3km`는 대표점 기준 **직선거리** 3km
이내 접점 수다. 같은 거리모형인 것처럼 해석하지 않는다.

`venues_jeonbuk.csv`는 전북특별자치도 2024-12-31 통합 파일 6,880건을 좌표화하고 SGIS
행정경계로 감사한 결과다. 6,856건이 좌표화됐고, 원천 시군과 좌표 시군이 일치한 6,854건만
자동 후보 풀에 둔다. 실패 24건과 불일치 2건은 별도 검토한다. 원천과 가공 산출물에 전화번호
필드가 없다. 목록 등재는 차량 진입·장소 사용·시간대 승인을 뜻하지 않는다.

`jeonbuk_route_scenario.json`은 전북 243개 대표점 중 도로거리 3km 초과 71개를 확인하고,
기본 도로거리 품질을 통과한 69개를 경로 대상으로 사용한다. 시군별 후보 간 거리는 OSM
일방통행을 반영한 방향성 최단거리이며, 시간은 40km/h 균일 속도 가정이다. 차량 3대·5일의
15개 경로일을 14개 시군에 최소 1일씩 배정하고 시군 내 선택방문 경로를 계산한다.
세부 입력·목표·출력은 `docs/SCENARIO_CONTRACT.md`를 따른다.
결과의 `covered_target_count`는 방문하는 행정동 대표점 대상 수다. 주민 커버리지·개선 인구는
제공하지 않으며 `resident_coverage_available=false`다. 각 대상의 같은 행정동에서 대표점과
직선으로 가장 가까운 경로당 1곳을 프록시로 연결한 것이므로 후보 위치 최적화도 아니다.
임계값과 운영 가정의 의존성은 `reports/scenario_evidence.md`에 수치로 공개한다.
`docs/demo-jeonbuk/data.js`는 별도 원천이 아니며 `access_road.csv`, `access_typology.csv`,
`jeonbuk_route_scenario.json`을 `src/build_dashboard_data.py`로 축약한 화면용 번들이다.
`docs/demo-jeonbuk/map-data.js`도 별도 원천이 아니다. `hjd2026.geojson`,
`south-korea-latest.osm.pbf`, 저장된 경로행렬을 `src/build_map_visualization.py`로 축약한다.
경로는 방향성 최단경로 좌표이며, 노드는 각 방향성 구간에서 최대 64개 표본만 포함한다.
원본 OSM·SGIS 파일이 Git 제외이므로 일반 팀원용 `verify_offline.sh`는 커밋된 번들의 구조와
경로-행렬 오차 메타데이터를 검증하고, 원천 갱신 담당자가 생성 스크립트를 다시 실행한다.

## 6. 현재 수치—행정동 대표점 프록시

- 전북 243개 행정동이 인구와 전부 조인된다.
- 65세 이상은 성별×65~110세이상 92개 컬럼 합계 470,160명이다.
- 직선거리: 중앙값 1.270km, 3km 초과 30개 대표점, 5km 초과 7개 대표점.
- 도로거리: 243개 모두 수치는 있으나 표준 239개+폴백 4개다. 표준 239개의 우회계수 중앙값은 1.383이다.
- 도로거리 3km 초과는 전체 71개 대표점, 5km 초과는 27개 대표점이다. 이 개수는 주민 노출 개수가 아니다.
- 임실군 운암면 대표점: 직선 최근접은 임실운암우체국 5.270km, 도로 최근접은 임실청웅우체국 9.874km다. 기존 12.51km 주장은 현재 라우팅 정의와 일치하지 않는다.

**중요:** `3km 초과 65세+ 몇 명`은 현재 산출하지 않는다. 행정동 대표점 하나의 거리를 행정동 전체 인구에 적용하면 농촌 대면적 읍·면에서 오차가 크다. 주민 단위 수치를 만들려면 SGIS/KOSIS 100m 또는 500m 격자별 65세+ 인구가 추가로 필요하다.

## 7. 도로망 재현 조건

- 전북 SGIS 전 섬역 경계의 외접상자에 0.25도 완충구역을 더한다.
- OSM 차량 통행 도로만 포함하고 비공개·차량통행금지 도로는 제외한다.
- 일방통행·회전교차로·고속도로 방향성을 반영한다.
- 전체 연결요소를 유지하며, 643개 접점을 동시 출발점으로 실행해 상위 12개 후보·cutoff가 없다.
- 시작점·종료점의 OSM 노드 연결구간을 도로거리에 포함한다.
- 여객선·도선 시간표를 포함하지 않는다. 섬 내 접점은 섬 내 도로망으로 계산한다.

## 8. 재현 순서

```bash
# 새마을금고 원천을 새로 받을 때만
PYTHONPATH=src .venv/bin/python src/collect_kfcc.py

PYTHONPATH=src .venv/bin/python src/collect_points.py
PYTHONPATH=src .venv/bin/python src/geocode.py
PYTHONPATH=src .venv/bin/python src/build_access.py
PYTHONPATH=src .venv/bin/python src/audit_geocodes.py
PYTHONPATH=src .venv/bin/python src/build_roadnet.py
PYTHONPATH=src .venv/bin/python src/analyze_coverage.py
PYTHONPATH=src .venv/bin/python src/build_typology.py
PYTHONPATH=src .venv/bin/python src/collect_venues.py
PYTHONPATH=src .venv/bin/python src/build_jeonbuk_route_scenario.py
PYTHONPATH=src .venv/bin/python src/build_scenario_evidence.py
PYTHONPATH=src .venv/bin/python src/build_dashboard_data.py
PYTHONPATH=src .venv/bin/python src/build_jeongeup_snapshot.py
PYTHONPATH=src .venv/bin/python src/validate_outputs.py
./verify_offline.sh

# 원천 스냅샷을 보유한 갱신 담당자만
./verify_source_lineage.sh
```

우체국 위치 API는 이 재현 순서에 없다.

## 9. 범위 한계와 추가로 필요한 데이터

- **주민 단위 접근성:** 100m/500m 격자별 65세+ 인구. 이것이 없으면 `3km 초과 고령인구`는 제출 수치로 쓸 수 없다.
- **우체국 현재 상태:** 우체국 위치 API 승인 또는 더 최신 공식 스냅샷. 현재는 2026-08-10 CSV로 상한한다.
- **은행 175건 전수성:** 전국은행연합회 공식 전체 내보내기 또는 조회별 수집 로그. 현재 파일만으로는 `1금융권 사실상 전부`를 입증하지 않는다.
- **전북 경로당 운영 가능성:** 69개 선택 후보별 장소 사용승인, 차량 진입, 실제 이용 가능 요일·시간.
- **순회 이동시간:** 현재 OSM 방향성 거리를 40km/h로 환산한 가정이며 현장 주행 또는 교통자료 보정이 필요하다.
- **시군 간 차량 재배치:** 현재 일정은 각 시군 후보 차고지에서 시작·복귀하며 전일 경로에서 다음 시군까지의 박차·숙박·재배치 시간은 모형화하지 않았다.

지역농협·축협 단위조합, ATM, 농어촌버스 배차간격은 별도로 문서화된 범위 한계다. 이 데이터셋이 포함한 것처럼 해석하지 않는다.

## 10. 재현 검증 경계

- `verify_offline.sh`: 깨끗한 Git 체크아웃의 커밋된 가공데이터·코드·문서 검증. 원본과 키 불필요.
- `verify_source_lineage.sh`: 원본 보유 환경의 파일 해시·수집로그·행정경계 포함관계 검증.
- GitHub Actions는 전자를 새 체크아웃에서 실행한다. 원본 비공개·대용량 조건 때문에 후자를 CI
  통과로 가장하지 않는다.

## 11. 개인정보·라이선스

공개 기관 목록, 공공 통계, 공개 도로망만 사용하며 개인·고객·거래 단위 자료를 사용하지 않는다. 재배포 조건은 `THIRD_PARTY_NOTICES.md`를 따른다.

## 부록: `access_road.csv` 보조 컬럼 정의

[서식 13] 데이터셋 설명서의 컬럼 정의서(주요 35열)에 싣지 않은 나머지 14열의 정의다.
전체 49열 = 주요 35열 + 아래 14열.

| 컬럼명 | 정의 |
|---|---|
| `nearest_outlet_id` | 최근접(분석 가용 기준) 접점의 내부 식별자 |
| `nearest_open_km` / `nearest_open_name` | 분석 가용(`finance_open_proxy_Y`) 접점 기준 최근접 직선거리·명칭. `nearest_km`·`nearest_name`과 같은 기준의 명시적 별칭 |
| `nearest_any_km` / `nearest_any_outlet_id` / `nearest_any_name` / `nearest_any_type` | 영업 상태 불문 전체 접점 기준 최근접 직선거리와 그 접점의 식별자·명칭·유형 |
| `distance_model` | 직선거리 산출 방식 라벨 (`largest_polygon_interior_point_straight_line`) |
| `road_outlet_id` / `road_nearest_name` / `road_nearest_type` | 도로거리 기준 최근접 접점의 식별자·명칭·유형 |
| `route_straight_km` | 도로거리 기준 최근접 접점까지의 직선거리 (우회계수 분모) |
| `max_snap_km` | 대표점·접점을 도로 노드에 붙일 때 허용한 스냅 거리 상한 (상수) |
| `admin_snap_strategy` | 대표점 스냅 방식 (`exact_nearest_node` 또는 도달 가능 노드 폴백) |
