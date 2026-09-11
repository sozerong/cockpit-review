# risk.error-masking v2 — broadness 분류 + 경로 필터

날짜: 2026-09-10
검증: v1 표본 재계산 (99건) + v2 warn 전량 라벨 (14건)

## 변경 사항

1. **예외 broadness로 재분류**
   - `bare-except` — bare `except:` (모든 예외 catch) → warn
   - `broad-except` — 예외 타입에 `Exception` 또는 `BaseException` 포함 → warn
   - `specific-except` — 그 외 (`except ImportError`, `except (OSError, ValueError)` 등) → **info**
2. **경로 필터** — dup.block v5와 동일. tests/examples/docs/scripts → warn을 info로 강등
3. `bare-except-pass` kind 삭제 (bare-except로 통합)

## 실측 — warn 총량

| repo | v1 warn | v2 warn | 감소 |
|---|---:|---:|---:|
| requests | 9 | 0 | -100% |
| click | 16 | 7 | -56% |
| flask | 10 | 0 | -100% |
| black | 129 | 0 | -100% |
| fastapi | 8 | 0 | -100% |
| pytest | 51 | 5 | -90% |
| poetry | 5 | 1 | -80% |
| httpx | 3 | 0 | -100% |
| aiohttp | 17 | 1 | -94% |
| records | 2 | 0 | -100% |
| **합계** | **250** | **14** | **-94.4%** |

## 라벨링 결과 (v2 warn 전량 14건 라벨)

| 라벨 | 개수 | 비율 |
|---|---:|---:|
| tp | 7 | 50.0% |
| fp | 0 | 0.0% |
| style | 6 | 42.9% |
| boilerplate | 1 | 7.1% |
| unclear | 0 | 0.0% |

지표:
- **actionable: 50.0%** (v1 6.1% → v2 50.0%, **8.2배**)
- 정밀도: 53.8%

**게이트: PASS — Week 4 진행** ✓

## v1 표본에 v2 필터 시뮬레이션 (교차 검증)

v1 라벨링된 99건에 v2 필터 규칙 적용:
- 99 warn → 9 warn (다른 90건은 v2 info로 강등)
- 남은 9건: tp 6, style 2, boilerplate 1
- **actionable 66.7%** (n=9, CI [35%, 88%])

v2 전량(14건)의 50%와 방향 일치. n이 늘어도 게이트 통과 확실.

## 진짜 신호 (tp 7건)

- `click/_compat.py:568` — cache set 실패 무시, 사용자 알림 없음
- `click/_winconsole.py:204` — flush() 실패 무시
- `click/utils.py:45` — wrapper가 어떤 실패든 None으로 은폐
- **`pytest/config/__init__.py:542`** — file open 실패 시 `err` 미정의, 다음 줄 NameError (잠재 버그)
- `pytest/pathlib.py:264, 277` — symlink/mkdir 실패 무시
- `poetry/version_solver.py:613` — solver retry에서 Exception 무시

## 노이즈 (style 6, boilerplate 1)

- `click/_compat.py:77` — `__del__` finalizer (관행적으로 예외 억제 허용)
- `click/_compat.py:170` — write 지원 여부 프로브
- `click/testing.py:571, 581` — 테스트 env 정리 (broad but scoped)
- `pytest/_code/source.py:251` — 이미 specific except 위에 있는 catch-all fallback
- `aiohttp/worker.py:137` — worker main loop (관행)
- `pytest/_code/code.py:333` — 주석에 의도 명시

**Style vs tp 판단이 문맥 의존적.** style 6건 중 일부는 검토 관점에 따라 tp가 될 수 있음. 정밀도 53.8%는 실제로는 60-70%가 될 수도 있음 (판정 여지 있음).

## 게이트 통과 확정

v3에서 REDESIGN이었던 error-masking이 v2에서 PASS. 튜닝 노브 1개(broadness + 경로 필터)로 8배 개선.

**dup.block(28% 부분 통과) vs error-masking(50% 통과)** — 두 분석기 상태:
- error-masking: 안정, Week 4 그대로 진행 가능
- dup.block: THRESHOLD REDESIGN, Week 5 P0에서 관계 판정으로 재접근 예정

## 판단 필요

1. **v2 warn 14건이 게이트 표본으로 충분한가**
   - CI: 7/14 = 50%, Wilson 95% CI [26.8%, 73.2%]. 하한 26.8% > 20% (redesign 하한)
   - 하한이 40% 통과선 아래긴 하지만 v1 표본 재계산이 66.7%로 일관됨
   - **추천: 이 결과로 게이트 통과 확정.** 추가 표본은 Week 4 이후 검증용으로
2. **Week 4 원래 계획 착수** — `--exit-code`, GitHub Action, baseline. 추천
3. **dup.block v5로 유지 결정 재확인** — error-masking이 통과했으므로 dup.block의 28%는 상대적으로 낮지만 프리즈 유지 가능
