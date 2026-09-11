# dup.block v1 — class-level exact 5-line windows

날짜: 2026-09-09
샘플: 10 repos, 2310 files scanned (black 타임아웃)

## 알고리즘

- 파일 전체를 5-line 슬라이딩 윈도우로 훑음 (import·decorator·class body 포함)
- 각 window를 `hash(text)`로 인덱싱, 2개 이상 등장 시 finding
- 파일 내 겹치는 window는 첫 것만 유지 (post-process dedupe)
- 필터: window의 non-blank 라인 ≥3

## 실측

| repo | files | dup findings |
|---|---:|---:|
| requests | 37 | 166 |
| click | 90 | 478 |
| flask | 83 | 347 |
| black | 343 | **타임아웃 (>15min)** |
| fastapi | 1138 | 14133 |
| pytest | 274 | 2924 |
| poetry | 447 | 3666 |
| httpx | 60 | 824 |
| aiohttp | 172 | 4298 |
| records | 9 | 4 |
| **합계** | 2653 | **26,840** (black 제외) |

## 원인 (샘플 확인)

fastapi 14k 중 상위 클러스터:
- `test_openapi_schema()` 스캐폴딩 224회 반복 (테스트마다 같은 클라이언트 호출)
- OpenAPI schema literal의 반복 라인 108, 104, 104, 104회
- `from fastapi import …` 같은 import stack

노이즈 종류:
1. **모듈 상단 import 스택** — 어느 파일이나 유사
2. **decorator 스택** (`@app.get(...)`)
3. **class body의 필드 스텁** (`self.a = None; self.b = None; ...`)
4. **테스트 스캐폴딩** — 각 test 파일이 동일한 `client = TestClient(app)` 초기화
5. **schema/dict 리터럴** — OpenAPI/JSON 데이터 반복

## 판정

**v1은 폐기.** 개별 라인 노이즈 필터로는 감당 불가. 근본적 재설계 필요.

## v2 방향

**함수 몸통에 한정.** module/class 최상위는 반복이 자연스러움. 진짜 로직 중복은 대부분 함수 안에 있음. tree-sitter로 `function_definition` 노드의 body만 windowing.
