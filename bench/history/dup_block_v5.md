# dup.block v5 — 경로 필터 확장

날짜: 2026-09-10
샘플: 동일 10 repos + 100건 재라벨링

## 변경 사항

`_is_test_path` → `_is_non_source_path`로 이름·의미 확장. 다음 경로 세그먼트를 non-source로 판정하여 severity 강등:
- `tests`, `test`, `testing`
- `examples`, `example`
- `docs_src`, `docs`, `doc`

파일명 규칙(`test_*.py`, `*_test.py`)은 유지.

## 실측 — warn 총량

| repo | v4 warn | v5 warn | 감소 |
|---|---:|---:|---:|
| requests | 10 | 10 | 0% |
| click | 47 | 44 | -6% |
| flask | 22 | 16 | -27% |
| black | 64 | 64 | 0% |
| fastapi | 241 | 132 | **-45%** |
| pytest | 365 | 82 | **-77%** |
| poetry | 39 | 39 | 0% |
| httpx | 151 | 151 | 0% |
| aiohttp | 187 | 146 | -22% |
| records | 2 | 2 | 0% |
| **합계** | **1,128** | **686** | **-39%** |

v3 대비 누적: 11,969 → 686 (**-94.3%**).

## 라벨링 결과 (100건 층화)

| 라벨 | 개수 | 비율 | v4 대비 |
|---|---:|---:|---|
| tp | 28 | **28.0%** | +6.8pt (21.2→28.0) |
| fp | 0 | 0.0% | — |
| style | 60 | 60.0% | +20.6pt (39.4→60.0) |
| boilerplate | 12 | 12.0% | -27.4pt (39.4→12.0) |
| unclear | 0 | 0.0% | — |

지표:
- **actionable: 28.0%** (v4 21.2% → v5 28.0%, v3 4.0% 대비 **7배**)
- 정밀도: 31.8% (v4 35.0%)

## 게이트 판정

**THRESHOLD REDESIGN — Week 4를 튜닝에 소진** (여전히 20~40% 구간, 통과선 40% 미달)

## 노이즈 재구성

boilerplate가 39 → 12로 급감. 남은 12건:
- fastapi `scripts/playwright/` 자동화 스크립트 5건 (경로 필터 놓침 — `scripts/` 추가 후보)
- docstring/Sphinx 지시어 필터 놓침 5건 (`:param:`, `..versionadded::`, class body docstring)
- deprecation warning 인자 블록 2건

**style이 지배적 (60%).** 이 중 httpx 18건 전부 Client/AsyncClient 병렬 클래스. 이 성격의 dup은 근본 처리하려면 병렬 클래스 감지가 필요 (v5 옵션 2, skip됨).

## 게이트 통과 조건 분석

40% 통과선 도달하려면:
- 현재 28건 tp / 100 → 40 이상 필요
- 또는 100 → 70건으로 줄이면서 tp 28 유지 → 40%

두 접근:
1. **더 많은 tp 발굴** — 병렬 클래스 감지 + 뮤테이션 기반 검증. 큰 작업, Week 5 P0 영역
2. **style 추가 필터** — Client/AsyncClient 페어 감지로 style 30건 필터하면 tp 28 / 70 → 40%

**현실적 판단**: v6 단순 필터 (scripts/ 추가) + 병렬 클래스 감지 heuristic 시도가 남은 옵션. 그 이상은 P0의 관계 판정과 겹침.

## src/-only 순수 정밀도

`src/`만 필터하면 실제 신호 밀도가 어떻게 되는지:

```
records: tp=2 (100%)
poetry: tp=5, style=2 → 71%
pytest src/: tp=5, style=7 → 42%
black src/: tp=5, style=4 → 56%
flask src/: tp=2, style=2 → 50%
aiohttp src/: tp=6, style=10 (boilerplate=2 docstring) → 33%
fastapi src/: tp=2, style=10 → 17%
click src/: tp=1, style=4 (boilerplate=2 docstring) → 14%
httpx src/: tp=0, style=18 (boilerplate=1 docstring) → 0%
requests src/: tp=0, style=3 (boilerplate=1) → 0%
```

**httpx/requests에서 tp=0.** 이 두 repo는 Client/AsyncClient 대칭이 지배적이라 병렬 클래스 감지 없이는 tp 나오기 어려움. 나머지 repo는 30% 이상.

## v6 방향 판단 사항

### 옵션 A — 단순 경로 필터 확장 (scripts/ 추가)
- 예상 boilerplate 12 → 7
- actionable 28/95 → 29.5% (미미)

### 옵션 B — 병렬 클래스 페어 감지
- 이름 매칭 heuristic: 같은 파일에 `Client` + `AsyncClient` 있으면 두 클래스 사이 dup은 severity 강등
- 예상 style 60 → 30-35 (httpx 18 + fastapi kwargs 몇 개 + pytest RaisesContext 페어)
- 리스크: 잘못된 페어 매칭으로 진짜 tp를 놓치면 회수율 하락. 정확도 검증 필요
- actionable 28/65 → 43% (게이트 통과)

### 옵션 C — 여기서 중단 (28%로 확정)
- Week 4 원래 계획 (`--exit-code`, GitHub Action) 병행
- v5로 릴리즈, 게이트는 "부분 통과"로 문서화
- error-masking 라벨링 착수

## 판단 필요

1. **v6 옵션 A/B/C 중 선택**
   - B는 통과선 도달하지만 heuristic 리스크
   - C는 게이트 실패 인정 + 다른 진행
2. **error-masking 층화 표본 병행 착수 여부** (dup.block v6 대기 중 병렬 진행 가능)
3. **재라벨링 예산** — 이번 라운드로 총 300건 라벨링 완료. 추가 라운드는 필요 시
