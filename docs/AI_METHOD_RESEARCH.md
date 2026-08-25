# AI·분석방법 보완 리서치

- 조사일: 2026-08-12
- 적용 대상: 2026 제4회 전북 청년 AI·빅데이터 경진대회 현안 해결 구현 분야
- 목적: AI 기능을 억지로 추가하지 않고 평가 가능한 분석·검증 증거를 설계한다.

## 요약

공식 요강은 AI나 생성형 AI를 사용하지 않아도 불이익이 없다고 명시한다. 따라서 LLM 챗봇보다
문제와 데이터에 맞는 탐색형 군집분석을 검증 가능하게 구현하고, 순회 경로는 시간창과 미방문을
포함한 운영최적화로 분리하는 편이 타당하다. 군집은 전북 전체를 강제로 섞지 않고 비교 가능한
읍·면 가운데 도로거리 품질을 통과한 행정동만 적합하며, 실루엣·전역 ARI·군집별 Jaccard·최소
군집 크기를 모두 확인한다.

## 확인된 사실

### F1. AI 사용은 필수가 아니다

- claim: 구현 분야는 데이터 분석, AI 분석, 생성형 AI, 시각화, 서비스 구현, 바이브 코딩 등 하나
  이상의 결과 형태를 허용하며 AI 미사용에 불이익이 없다고 명시한다.
- source: [전북대학교 공식 공고](https://software.jbnu.ac.kr/bbs/software/527/394930/artclView.do),
  [공식 요강 HWP](https://software.jbnu.ac.kr/bbs/software/527/353895/download.do)
- source_type: official_docs
- author_or_team: 전북 인공지능·데이터 공동연구회 / 전북대학교 빅데이터 혁신융합대학사업단
- published_at: 2026-06-22
- accessed_at: 2026-08-12
- confidence: high

### F2. 평가항목은 방법의 타당성과 구현 증거를 함께 본다

- claim: 구현 분야 평가항목은 문제 해결성, 데이터 활용성, 분석·AI 방법 적합성, 구현 완성도,
  파급성·활용성, 발표력이다. 공개 첨부자료에서 수치 배점은 확인되지 않았다.
- source: [공식 요강 HWP](https://software.jbnu.ac.kr/bbs/software/527/353895/download.do)
- source_type: official_docs
- published_at: 2026-06-22
- accessed_at: 2026-08-12
- confidence: high

### F3. AI 활용 과정과 참가자 검증을 공개해야 한다

- claim: AI 또는 바이브 코딩을 사용하면 도구, 활용 범위·과정, 참가자의 수정·검토와 검증을
  밝혀야 하며 검증되지 않은 AI 생성 통계·출처·코드·분석은 제출 위험이다.
- source: [공식 요강 HWP](https://software.jbnu.ac.kr/bbs/software/527/353895/download.do),
  [공식 코드 제출 안내 PDF](https://software.jbnu.ac.kr/bbs/software/527/353893/download.do)
- source_type: official_docs
- published_at: 2026-06-22
- accessed_at: 2026-08-12
- confidence: high

### F4. 실루엣만으로 군집을 채택할 수 없다

- claim: 실루엣은 군집 내부 응집도와 다른 군집과의 분리를 비교하지만, 하나의 내부지표가 군집의
  실제 정책적 의미까지 보증하지 않는다.
- source: [Rousseeuw 1987](https://www.sciencedirect.com/science/article/pii/0377042787901257),
  [von Luxburg 2010](https://arxiv.org/abs/1007.1075)
- source_type: research_paper
- published_at: 1987-11-01 / 2010-07-07
- accessed_at: 2026-08-12
- confidence: high

### F5. 군집별 안정성을 따로 봐야 한다

- claim: 재표집 결과를 원 군집과 Jaccard로 대응시키면 군집별 안정성을 평가할 수 있으며, 전역
  안정성 하나는 특정 군집의 불안정을 가릴 수 있다.
- source: [Hennig 2007](https://www.homepages.ucl.ac.uk/~ucakche/papers/clusta.pdf),
  [von Luxburg 2010](https://arxiv.org/abs/1007.1075)
- source_type: research_paper
- published_at: 2007-09-15 / 2010-07-07
- accessed_at: 2026-08-12
- confidence: high

### F6. 모집단과 적용 범위를 먼저 정의해야 한다

- claim: 군집의 목적과 결과가 적용되는 모집단을 명시해야 하며, 관측된 대상에서 찾은 군집이
  다른 모집단으로 자동 일반화되지는 않는다.
- source: [Hennig 2015](https://discovery.ucl.ac.uk/id/eprint/1467289/)
- source_type: research_paper
- published_at: 2015
- accessed_at: 2026-08-12
- confidence: high

### F7. 시간창 경로문제는 거리 외 운영입력이 필요하다

- claim: 시간창 차량경로문제는 이동시간 행렬, 거점별 시간창, 출발지·차량, 대기, 운행 한도와
  서비스시간이 필요하다. 모든 후보를 방문할 수 없다면 미방문을 허용하고 결과에 남겨야 한다.
- source: [Solomon 1987](https://pubsonline.informs.org/doi/10.1287/opre.35.2.254),
  [OR-Tools VRPTW](https://developers.google.com/optimization/routing/vrptw),
  [OR-Tools 미방문 페널티](https://developers.google.com/optimization/routing/penalties)
- source_type: research_paper / official_docs
- published_at: 1987-04-01 / unknown
- accessed_at: 2026-08-12
- confidence: high

## 적용 판단

1. 생성형 AI 챗봇은 추가하지 않는다. 평가상 필수가 아니고 금융상품·상담으로 범위가 확대된다.
2. AI·분석 모델은 전북 243개 전체가 아니라 비교 가능한 농촌 읍·면과 기본 도로거리 품질을
   통과한 155개를 적합 모집단으로 사용한다.
3. 입력은 OSM 도로거리, 대표점 기준 직선 3km 내 접점 수, 65세 이상 비율로 제한한다. 서로
   다른 거리 정의를 명시하며, 중첩된 1·3·5km 접점 수를
   동시에 넣어 같은 개념을 반복 가중하지 않는다.
4. Ward 계층 군집의 `k=2..5`를 비교하고 실루엣, 80% 재표집 ARI, 군집별 Jaccard, 최소 군집
   크기를 모두 통과한 경우에만 탐색형 라벨을 공개한다.
5. km·접점 수·비율의 선형 의미를 보존한 강건 표준화를 주 전처리로 사용하되, 거리와 접점
   수를 `log1p`로 압축한 대안과의 ARI 0.75 이상·군집별 최적 대응 Jaccard 최솟값 0.70 이상을
   프로젝트 채택 게이트로 둔다.
6. 모델 라벨은 정책순위가 아니다. 규칙형 유형과 원지표를 함께 제공하고 도로거리 폴백은
   미분류·불확실성으로 표시한다.
7. 경로는 AI가 아니라 운영최적화로 설명한다. 향후 1차 목적은 우선대상 방문 수 최대화,
   2차 목적은 이동시간 최소화로 분리하고, 미방문 거점과 제약 위반을 출력한다.

## 모순과 주의

- `AI가 필수다`라는 가정은 공식 요강과 모순된다.
- 안정적인 군집이 반드시 정책적으로 타당한 군집이라는 뜻은 아니다. 유형별 원지표와 대표
  읍·면을 사람이 검토해야 한다.
- 선택 모델 `k=2`도 로그 전처리 대안과 소속이 완전히 같지 않다(ARI 0.779). 이 민감도를 숨기지 않고
  탐색형 라벨·규칙형 유형·원지표를 함께 보여준다.
- OSM 길이와 속도 가정으로 만든 시간은 자유흐름 추정치이며 실제 교통시간이 아니다.
- 최적화 도구가 실행 가능한 해를 반환해도 전역 최적성을 별도로 입증하지 않았다면 `최적`을
  확정적으로 주장하지 않는다.

## 남은 공백

- 공개 요강에서 평가항목별 수치 배점은 확인되지 않았다.
- 전북 14개 시·군의 실제 후보 거점, 사용 가능시간, 출발·복귀지, 서비스시간은 아직 운영 가정이다.
- 현재 도로망은 거리 중심이며 검증된 이동시간 행렬이 없다.
- 유형의 시점 안정성을 보려면 다음 데이터 갱신 시 같은 검증을 반복해야 한다.
- 공식 AI 활용계획서·윤리서약 등 제출 서식은 최종 제출 시 참가자가 별도로 확인·작성해야 한다.
