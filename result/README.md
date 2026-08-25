# result — 분석 결과

## reports/ — 사람이 읽는 결과 문서

| 파일 | 내용 |
|---|---|
| `quality_report.md` | 데이터 품질·검증 항목과 남은 한계 |
| `coverage_by_sigungu.md` | 시군별 접근성 커버리지 |
| `typology_evaluation.md` | 군집 후보 `k=2..5` 채택·기각 근거 |
| `scenario_evidence.md` | 임계값·방문상한·속도·서비스시간 민감도 감사 |

## outputs/ — 최종 산출물

| 파일 | 내용 |
|---|---|
| `access_jeonbuk.csv` | 행정동 243개 직선거리 접근성 |
| `access_road.csv` | 행정동 243개 OSM 도로거리 접근성 |
| `access_typology.csv` | 행정동 243개 취약유형 라벨 |
| `coverage_by_sigungu.csv` | 시군별 집계 |
| `outlets_validated.csv` | 검증 완료 금융 접점 681건 |
| `ecos_jeonbuk_loans_202508_202605.csv` | ECOS 전북 원화대출금 공개 샘플 10개월 |
| `jeonbuk_route_scenario.json` | 차량 3대·5일 순회 배정 결과 |
| `scenario_evidence.json` | 민감도 감사 원자료 |
| `typology_evaluation.json` | 군집 채택 게이트 지표 |

이 파일들은 `data/processed/`에서 재생성되는 산출물의 사본이다.
`bash verify_offline.sh`를 돌리면 `data/processed/` 쪽이 다시 계산되며,
두 위치의 내용은 같아야 한다.

## 시각화 결과

대시보드와 지도는 `docs/demo-jeonbuk/index.html`을 브라우저로 열면 된다.
계산 수식·군집·경로 이론 설명은 `docs/demo-jeonbuk/methodology.html`에 있다.
