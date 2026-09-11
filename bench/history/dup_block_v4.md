# dup.block v4 — nested-fn dedupe + string-dominant skip + tests/ severity 강등

날짜: 2026-09-10
샘플: 동일 10 repos, 이번엔 black 포함 완료

## 변경 사항

1. **Nested function 중복 방출 버그 수정** — outer/inner body가 겹치는 5줄에 대해 동일 `(start_line, text)` 튜플이 두 번 emit되던 문제. `_windows_in_bodies`에서 dedupe. v3의 `copies=1` 리포터 버그 원인.
2. **String-dominant window 제외** — tree-sitter `(string)` 노드의 byte 범위와 window의 byte 범위 겹침을 계산, 60% 이상이면 스킵. Docstring, JSON schema literal, CLI 출력 리터럴, HTML 리터럴 등.
3. **tests/ severity 강등** — `_is_test_path()` 매칭 시 `warn` → `info`. 파일명 `test_*.py`, `*_test.py`, 경로에 `tests` 또는 `test` 세그먼트 포함.

## 실측 — warn 총량 (v3 → v4)

| repo | v3 warn | v4 warn | 감소 |
|---|---:|---:|---:|
| requests | 131 | 10 | -92% |
| click | 302 | 47 | -84% |
| flask | 228 | 22 | -90% |
| black | 557 | 64 | -89% |
| fastapi | 3225 | 241 | -93% |
| pytest | 2137 | 365 | -83% |
| poetry | 1984 | 39 | -98% |
| httpx | 456 | 151 | -67% |
| aiohttp | 2947 | 187 | -94% |
| records | 2 | 2 | 0% |
| **합계** | **11,969** | **1,128** | **-90.6%** |

목표 -85% 초과 달성.

## 라벨링 결과 (99건 층화 재표본)

| 라벨 | 개수 | 비율 |
|---|---:|---:|
| tp | 21 | 21.2% |
| fp | 0 | 0.0% |
| style | 39 | 39.4% |
| boilerplate | 39 | 39.4% |
| unclear | 0 | 0.0% |

- **actionable (tp / labeled): 21.2%** — v3 4.0% 대비 **5.3배 증가**
- 정밀도 (tp/(tp+fp+style)): 35.0%

## 게이트 판정

**THRESHOLD REDESIGN — Week 4를 튜닝에 소진** (20~40% 구간)

v3 REDESIGN에서 한 단계 올라옴. 살아남은 노이즈의 성격이 완전히 다름:
- v3: boilerplate 지배 (docstring, JSON schema, 테스트 스캐폴딩)
- v4: **style이 boilerplate와 동률** — 병렬 클래스 대칭 (Client/AsyncClient), kwargs forwarding, symmetric method pairs

## 남은 노이즈 원인

### boilerplate 39건 세부

| 소분류 | 개수 | 대응 |
|---|---:|---|
| pytest `testing/` 디렉토리 | 18 | `_is_test_path`에 `testing/` 세그먼트 추가 |
| fastapi `docs_src/` 튜토리얼 | 10 | 경로 필터 확장: `docs_src/`, `docs/src/` |
| flask/aiohttp `examples/` | 6 | 경로 필터 확장: `examples/`, `example/` |
| docstring string filter miss | 3 | tree-sitter query 확장: `(concatenated_string)` 등 |
| deprecation warning / string arg block | 2 | `warnings.warn(...)` 인자 블록 감지 |

**전부 경로 필터 확장으로 해결 가능.** `_is_test_path` → `_is_non_source_path` 확장으로 이름 변경.

### style 39건 세부

| 소분류 | 개수 | 판정 |
|---|---:|---|
| httpx `Client` vs `AsyncClient` 대칭 | 13 | 병렬 클래스 — 자동 감지 후 severity 강등 |
| fastapi kwargs forwarding (params.py, encoders.py) | 8 | `**kwargs` 후 `super().__init__(**...)` 패턴 감지 |
| aiohttp 대칭 메서드 (send_heartbeat 등) | 6 | 클래스 내 pair 감지 |
| pytest RaisesContext / RaisesGroup 대칭 | 6 | 병렬 클래스 |
| click Windows console text/binary 대칭 | 3 | 병렬 함수 |
| black kwargs forwarding | 1 | — |
| 기타 | 2 | — |

**style은 근본 처리 어려움.** "병렬 클래스 감지"는 이름 매칭 휴리스틱이 필요 (Client-AsyncClient, Base-Sub, sync-async 접두어/접미어). v5 후보이나 정확도 리스크 큼.

## v5 방향 (제안, 확정 아님)

**옵션 1: 경로 필터 확장 (안전)**
- `_is_test_path` → `_is_non_source_path` 확장
- 추가: `testing/`, `examples/`, `docs_src/`, `docs/`, `docs/`.
- 예상 효과: boilerplate 39 → ~5, actionable 비율 21.2% → **31.9%** (Week 4 게이트 통과 임박)

**옵션 2: 병렬 클래스 감지 (리스크)**
- `Client` / `AsyncClient`, `SyncFoo` / `AsyncFoo` 이름 매칭 → 클래스 페어 감지
- 페어 내부 dup은 severity 강등
- 예상 효과: style 39 → ~15 (남는 것은 kwargs forwarding 등)
- **리스크**: 이름 매칭 heuristic이 부적절한 페어 매칭 시 진짜 tp 놓칠 수 있음

**추천: 옵션 1만 v5로 실행.** 옵션 2는 P0 파일럿(Week 5)에서 이 문제를 더 정교하게 다룰 예정 (관계 판정과 같은 방향).

## v4 → v5 예상 게이트

옵션 1 적용 시:
- boilerplate 39 → ~5 (경로 필터가 잡는 게 34건)
- 총 라벨링 대상 유지 60건 → tp 21, style 34, boilerplate 5
- actionable = 21/60 = **35%** → PASS 임박
- v5 후 재라벨링 필요할 수 있음 (본 표본은 v4 warn 기준이라 v5 필터 적용 시 표본 자체가 바뀜)

## 판단 필요

**당신이 결정할 것:**
1. v5 옵션 1 진행 여부 (경로 필터 확장) — 1시간 미만 예상. 추천
2. v5 후 재라벨링 100건 vs 표본 재활용 (v4 표본 중 filtered 제외분만 계산) — 후자가 빠름
3. error-masking 층화 표본 병행 여부 — 이번 라운드 결과 나오면 다음 순서
