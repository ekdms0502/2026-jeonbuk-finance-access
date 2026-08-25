# 오픈소스·외부 데이터 고지

## 코드 의존성

| 구성요소 | 사용 범위 | 출처 | 라이선스 |
|---|---|---|---|
| pyosmium 4.3.1 | OpenStreetMap PBF 읽기 | https://github.com/osmcode/pyosmium | BSD-2-Clause |
| NumPy 2.4.6 | 군집 입력 변환·수치 계산 | https://numpy.org/ | BSD-3-Clause |
| SciPy 1.17.1 | Ward 계층 군집·거리행렬 | https://scipy.org/ | BSD-3-Clause |
| Pretendard Variable | 대시보드·문서 번들 웹폰트 (`docs/fonts/`) | https://github.com/orioncactus/pretendard | SIL OFL 1.1 (전문: `docs/fonts/LICENSE.txt`) |

그 밖의 Python 코드는 표준 라이브러리를 사용한다.

## 외부 데이터

- 행정동 경계는 통계청 SGIS 원천과 vuski/admdongkor 가공물을 사용하며 SGIS 출처표시와
  재배포본의 CC BY 4.0 조건을 유지한다.
- OpenStreetMap 도로망은 Open Database License(ODbL) 1.0을 따르며 Geofabrik 공개 추출본을 사용한다.
- 우정사업본부 우체국 정보와 전북특별자치도 시군 경로당 6,880건 원천은 공공데이터포털의
  `이용허락범위 제한 없음` 표시를 따른다. 원천 컬럼은 시군명·경로당명·주소로,
  전화번호를 포함하지 않는다.
- 행정안전부 주민등록 인구통계, 은행연합회·신협·새마을금고 공개 조회, 카카오 로컬 API,
  한국은행 ECOS는 각 원천 페이지와 이용조건을 표시하고 원본 재배포 여부를 분리한다.
- 그 밖의 데이터 제공기관, 파일별 수집일, 재현 경로는 `DATASETS.md`에 정리했다.
- 원천별 정확한 URL·질의·기준일·수집일·SHA-256·분석 역할은 `data/source_manifest.json`에 정리했다.
- 원본 데이터는 크기와 재배포 조건 때문에 저장소에 포함하지 않고, 가공 산출물과 설명만 공유한다.
