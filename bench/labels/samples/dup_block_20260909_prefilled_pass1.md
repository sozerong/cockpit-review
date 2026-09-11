# dup.block 라벨링 — pass 1 (자동 힌트 + 8건 초안 판정)

날짜: 2026-09-09
샘플: 101건 (10 repos 층화)

## 자동 힌트 (21건, ~21%)

프로그램적으로 명확히 판단 가능한 것만 자동 라벨:
- **docstring**: `"""` 또는 `Args:` / `Returns:` / `Raises:` 섹션 포함 → `boilerplate`
- import stack (≥3 import), decorator stack (≥3 @), `__init__` field stubs (≥4 self.x=)

실측: **21/101 = docstring 100%**. import/decorator/field stub은 v2에서 이미 제거됨을 재확인.
→ v4 최우선 노브: **docstring 제외**.

## 나머지 80건 중 8건 대표 샘플 (사람 검토용 초안)

| repo | file:line | 초안 | 근거 |
|---|---|---|---|
| aiohttp | payload.py:781 | **tp** | chunk read + `min(DEFAULT_CHUNK_SIZE, ...)` 로직이 2곳 반복. 헬퍼 추출 가치 있음 |
| black | __init__.py:1600 | unclear | matches_count=1로 표시됨 — 리포터 버그 의심 (cluster 크기 2인데 matches 비어 보임) |
| click | testing.py:488 | tp | `hidden_input` 함수 정의 형태가 2곳에 나타남. 명확한 복붙 |
| fastapi | applications.py:4231 | **boilerplate** | 실제 docstring 안의 markdown 코드 예제 블록. 자동 힌트가 놓친 case (backtick 사이의 예시) |
| flask | tests/test_basic.py:183 | boilerplate | HTTP method 별 status/body 검증 — 테스트 성격상 반복이 자연스러움 |
| httpx | _client.py:687 | boilerplate | `Client` vs `AsyncClient` 초기화가 대칭적으로 반복 — 리팩터링 강요 안됨 |
| poetry | test_add_plugins.py:98 | boilerplate | CLI 출력 문자열 리터럴 (`Updating dependencies\n...`). 여러 테스트가 같은 패키지 설치 결과를 검증 |
| pytest | hookspec.py:821 | boilerplate | docstring 안의 `:hook:` cross-ref 블록. 자동 힌트가 놓친 case (Sphinx 지시어) |

**8건 초안 요약:** tp 2, boilerplate 5, unclear 1

## 관찰 (v4 힌트 후보)

1. **자동 힌트에서 놓친 docstring 하위 패턴**: `:hook:` / `:param:` Sphinx 지시어, markdown 코드 예시(backtick)
2. **테스트 파일**: flask/poetry/pytest 샘플이 전부 `tests/` 안. 테스트 파일은 별도 정책 필요할 것으로 보임 (예: severity 강등, 또는 test dir는 위치 threshold를 낮춤)
3. **문자열 리터럴 지배 window**: poetry sample처럼 code보다 string이 window의 대부분인 경우 → 별도 필터 후보

## 다음 액션

1. 사람이 나머지 80건 라벨링 (예상 소요: 1시간)
2. `python bench/label.py score dup.block bench/labels/samples/<완료된_csv>` → 지표 자동 계산 + `bench/labels/scores/`에 저장
3. 지표 나오면 v4 방향 결정 (docstring 제외만 해도 상당량 감소 예상)
