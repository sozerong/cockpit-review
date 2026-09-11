# dup.block v3 — collapse widespread clusters

날짜: 2026-09-09
샘플: 동일 10 repos + black 포함

## 알고리즘 변경

- v2 위에: 클러스터 크기 > 5 (_ACTIONABLE_MAX)이면 첫 위치에 `info` 1개만 emit
  - `evidence.total_matches` = 전체 위치 수
  - `evidence.matches` = 상위 5개 예시만
- 2-5회 클러스터는 그대로 `warn` × N (진짜 복붙은 위치마다 표시)

## 실측 — dup 총량

| repo | v1 | v2 | v3 | v3 warn / info |
|---|---:|---:|---:|---|
| requests | 166 | — | 132 | 131 / 1 |
| click | 478 | 305 | 304 | 302 / 2 |
| flask | 347 | 233 | 228 | 228 / 0 |
| black | timeout | 588 | 562 | 557 / 5 |
| fastapi | 14133 | 8149 | 3506 | 3225 / 281 |
| pytest | 2924 | 2280 | 2165 | 2137 / 28 |
| poetry | 3666 | 2426 | 2044 | 1984 / 60 |
| httpx | 824 | 521 | 469 | 456 / 13 |
| aiohttp | 4298 | 3457 | 3026 | 2947 / 79 |
| records | 4 | 2 | 2 | 2 / 0 |

**성과 (v1 대비):**
- 총량 -~70% (fastapi 특히 -75%)
- 대규모 boilerplate 클러스터는 단일 info로 축약됨
- warn 카운트 = "실제 리뷰해야 할 것"에 근접 (아직 검증 필요)

## 남은 문제

- fastapi warn 3225: 2-5회 클러스터가 여전히 다수. 라벨링으로 성격 확인 필요
- aiohttp warn 2947: 유사
- 아직 hand-label 없음 → v4 방향은 데이터가 결정

## v4 방향 (미정, 라벨링 후)

가능성:
- window 5→7로 증가 (짧은 반복 제거)
- 테스트 파일 제외 (`test_*.py`) — 다만 진짜 테스트 중복은 놓침
- 함수 signature 유사도 (지금은 body만 비교; 함수 목적이 완전히 달라도 body 5줄이 같으면 flag)

**판단 유예 — 라벨링 결과 없이 heuristic 더 만지지 않음. PLAN §4 원칙.**
