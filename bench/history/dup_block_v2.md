# dup.block v2 — function-body only

날짜: 2026-09-09
샘플: 동일 10 repos (v1과 비교 가능)

## 알고리즘 변경

- tree-sitter `(function_definition body: (block))` 쿼리로 함수 body만 추출
- body 내부에서만 5-line 윈도우 생성
- 추가 필터: window의 distinct non-blank 라인 ≥3 (반복 boilerplate 방지)
- 나머지는 v1과 동일 (해시 매칭, per-file overlap dedupe)

## 실측

| repo | v1 | v2 | 변화 |
|---|---:|---:|---:|
| requests | 166 | (재실행 안함) | — |
| click | 478 | 305 | -36% |
| flask | 347 | 233 | -33% |
| black | 타임아웃 | 588 | ✓ 완료 |
| fastapi | 14133 | 8149 | -42% |
| pytest | 2924 | 2280 | -22% |
| poetry | 3666 | 2426 | -34% |
| httpx | 824 | 521 | -37% |
| aiohttp | 4298 | 3457 | -20% |
| records | 4 | 2 | — |

**성과:**
- 총량 ~30-40% 감소
- black 타임아웃 해결 (14k+ windows가 사라짐)
- 실측 없이도 예측 가능한 노이즈 클래스 제거

## 남은 문제

fastapi 8149 클러스터 재확인 → 여전히 224회 반복되는 `test_openapi_schema` 스캐폴딩이 상위. 함수 몸통이라도 224번 반복되면 관찰 가능한 노이즈.

원인: **테스트 스캐폴딩은 함수 몸통 안에 있다.** v2 필터로는 잡히지 않음.

## v3 방향

**대규모 클러스터 축약.** 6+ 위치에서 반복되는 window는 `warn` × N개 대신 `info` 1개로 축약. 진짜 복붙 (2-5회)은 그대로 `warn` 유지. 위치 카운트가 곧 "widespread boilerplate"의 신호.
