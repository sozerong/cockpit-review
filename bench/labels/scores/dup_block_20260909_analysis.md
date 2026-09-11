# dup.block pass 1 — 라벨링 결과 분석 + 판단 필요 사항

날짜: 2026-09-09
라벨링 주체: Claude (초안), 사람 검토 필요
표본: 101건 (10 repos 층화)

## 핵심 수치

| 지표 | 값 | 의미 |
|---|---:|---|
| actionable (tp / labeled) | **4.0%** | 100건 중 4건만 진짜 문제 |
| precision (tp / (tp+fp+style)) | 66.7% | 노이즈만 걷어내면 나머지는 대부분 맞음 |
| boilerplate 비중 | **83.2%** | 압도적 |
| 오탐(fp) | 0 | 완전히 틀린 판정은 없음 |
| unclear (reporter bug) | 10.9% | copies=1로 표시된 이상 케이스 |

**게이트 판정: REDESIGN.** actionable 4% < 20%.

## 노이즈 구성 (boilerplate 84건 세부)

| 유형 | 대략 건수 | 예시 |
|---|---:|---|
| Docstring (자동 힌트) | 21 | `"""..."""`, `Args:/Returns:` |
| Docstring 자동 힌트 놓친 것 | ~5 | Sphinx `:hook:` 지시어, markdown ```python 코드 예 |
| JSON/OpenAPI schema 리터럴 | ~15 | fastapi 테스트의 기대 응답 dict |
| 테스트 스캐폴딩 | ~30 | `client = TestClient(app); response = client.get(...)` |
| 테스트 fixture data | ~5 | black의 tests/data/cases/*.py 포매터 코퍼스 |
| 병렬 클래스 대칭 코드 | ~5 | Client vs AsyncClient, SockSite vs TCPSite |
| CLI 출력 문자열 리터럴 | ~3 | poetry 테스트의 "Updating dependencies\n..." |

**결론: 노이즈의 소스는 4가지 정도로 명확히 분리됨. 각각 필터링 가능.**

## 진짜 신호 (tp 4건)

- `aiohttp/payload.py:781` — chunk-read `min(DEFAULT_CHUNK_SIZE, ...)` 로직 2곳
- `fastapi/routing.py:1610` — routing candidates loop 2곳
- `records/records.py:411 + :431` — 파일 경로 validation 완전 동일 2곳 (extract to `_validate_path`)

관찰: **`src/`에 있는 코드에서만 tp가 나옴.** `records`는 tests가 거의 없는 단일 파일 라이브러리 → 100% actionable.

## 리포터 버그 (unclear 11건)

`copies=1`로 표시된 dup finding 존재. dup.block은 정의상 ≥2 위치. 원인:
- 가설 1: 같은 파일 내 겹치는 두 window가 dedupe로 하나 남았는데 `matches` 리스트가 비어 있음
- 가설 2: `evidence.matches` 직렬화 이슈

**우선순위 중간.** 라벨링에 영향은 있지만 v4 재설계와 무관하게 고칠 것.

## 판단 필요 사항 (당신이 결정)

### 1. dup.block v4 방향 (필수 결정)

| 옵션 | 예상 효과 | 리스크 |
|---|---|---|
| **A. 최소한 (docstring 확장 + 문자열 우세 window 제외)** | 노이즈 -50%, actionable ~10% | v4로도 게이트 못 통과할 수 있음 |
| **B. 중간 (A + `tests/` 폴더 severity 강등을 info로)** | 노이즈 -85%, actionable ~30% | 진짜 테스트 dup 놓침 (하지만 P0에서 별도로 잡을 예정) |
| **C. 공격적 (B + JSON/schema literal 감지 후 제외)** | 노이즈 -95%, actionable ~50% | 구현 복잡도 상승 (AST literal 판별) |

**추천: B.** 이유:
- 노이즈의 대부분이 tests/ 안에 있음 (fastapi, poetry, pytest, aiohttp 전부)
- `tests/` 안의 dup은 실제로 "리팩터링 해야 한다"보다 "테스트 fixture로 뽑자"라는 별도 판단
- severity 강등이면 정보는 남기고 warn 소음은 죽임
- src/ 코드의 정밀도가 66.7%로 이미 쓸만함 — 노이즈만 걷어내면 됨

### 2. error-masking 라벨링 진행 방식 (선택)

현재 unique.csv 191건 존재. 옵션:
- 전량 라벨링 (1-2시간)
- 층화 표본 50-80건 (30분)
- 미룸 (Week 4 이후)

error-masking은 이미 게이트 조건 유리(ruff와 겹침 24%, 고유 76%). 소량 라벨링해도 판정 가능할 것으로 예상.

### 3. Week 4 일정 (필수 결정)

원래 PLAN §2 Week 4: `--exit-code`, 설정 파일, GitHub Action.
지금 상황:
- dup.block REDESIGN 필요 (v4)
- error-masking 라벨링 미완료

옵션:
- **A. dup.block v4에 Week 4 전체 소진** — 원래 PLAN §4의 "임계값 재설계에 4주차를 전부 쓴다" 시나리오 그대로
- **B. dup.block v4는 2일, 남은 3일을 원래 Week 4 계획으로** — 릴리즈 형태 유지가 목적이면
- **C. dup.block을 잠시 off (분석기 리스트에서 빼기), Week 4 원래 계획대로 + Week 5 P0로 이동** — dup.block을 이번 6주 산출물에서 뺌

**추천: A.** 이유:
- Track B의 6주 목표에 "오탐률 실측치"가 명시됨. dup.block off로 릴리즈하면 tp:fp 비율이 error-masking 하나로만 결정 → 대표성 떨어짐
- v4 옵션 B는 이미 명확한 필터 목록이 있어서 2-3일이면 구현 가능
- 남은 Week 4 시간에 `--exit-code`, baseline, GitHub Action 병행 가능

### 4. 리포터 버그 (선택)

`copies=1` 케이스 조사 우선순위:
- Week 4 초반 (v4 착수 전)
- v4 완료 후
- 별도 이슈로 남기고 미룸

**추천: v4 착수 전 30분.** matches 리스트 empty가 되는 정확한 코드 경로 찾아 fix. 라벨링 재현성에 필요.

## 재라벨링 검토가 필요한 판정 (당신이 다시 볼 곳)

Claude가 판단 자신 없거나 문맥 부족한 케이스 15건:
- click/tests/test_commands.py:615 (test decorator setup — style로 볼지 boilerplate로 볼지)
- fastapi/scripts/doc_parsing_utils.py:449 (error message dup — style vs tp)
- httpx/_client.py:687, 1630 (Client vs AsyncClient — style vs boilerplate)
- 그 외 unclear 11건 (reporter bug 해결 후 재분류 필요)

CSV의 `label` 컬럼을 직접 수정 후 `python bench/label.py score dup.block <path>` 재실행하면 지표 재계산됨.
