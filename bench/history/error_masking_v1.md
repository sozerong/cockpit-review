# risk.error-masking v1 — 라벨링 결과

날짜: 2026-09-10
표본: 99건 층화 (10 repos, seed=45)

## 알고리즘 (v1 현재)

3가지 패턴 감지:
- `bare-except` — `except:` (예외 타입 없음)
- `bare-except-pass` — bare + body가 `pass` 또는 `...`
- `empty-except-body` — 예외 타입은 명시했으나 body가 `pass` 또는 `...`

## 라벨링 결과

| 라벨 | 개수 | 비율 |
|---|---:|---:|
| tp | 6 | 6.1% |
| fp | 0 | 0.0% |
| boilerplate | 88 | 88.9% |
| style | 5 | 5.1% |
| unclear | 0 | 0.0% |

지표:
- **actionable: 6.1%**
- 정밀도: 54.5%

**게이트: REDESIGN**

## evidence.kind별 분석 (이게 핵심 발견)

| kind | 표본 수 | tp | actionable |
|---|---:|---:|---:|
| bare-except | 3 | 1 | 33% |
| empty-except-body | 96 | 5 | 5.2% |

## 핵심 관찰

**모든 tp는 broad exception (bare, `except Exception:`)이었고, 모든 boilerplate/style은 specific exception이었음.**

tp 6건 exception 타입:
- click _winconsole.py:204 — `except Exception: pass` in flush()
- click utils.py:45 — `except Exception: pass` in wrapper → return None
- poetry version_solver.py:613 — `except Exception: pass` in solver retry
- pytest pathlib.py:264 — `except Exception: pass` on symlink
- pytest pathlib.py:277 — `except Exception: pass` on mkdir
- records records.py:344 — `except:` (bare) in transaction, no re-raise

boilerplate 88건 exception 타입 분포:
- Optional import fallback (`except ImportError: pass`) — ~15
- Test data corpus (black `tests/data/cases/*.py`) — 34
- Test intentional trigger (`except Exception: pass` in test) — ~10
- Cache miss (`except KeyError: pass`) — ~5
- Cleanup (`except OSError: pass`) — ~5
- 도메인 특수 (`StopIteration`, `EACCES`, `EndOfStream` 등) — 나머지

## 결론

**error-masking v1은 근본적으로 잘못 계층화되어 있음.**
- `empty-except-body` 카테고리가 너무 넓음: `except ImportError: pass`부터 `except Exception: pass`까지 모두 같은 warn 취급
- 실제로는 예외 타입의 **broadness**가 유일한 신호

## v2 제안 (선명함)

기존 3개 kind를 4개로 재분류:
- `bare-except` — bare `except:` (모든 예외 catch) → **warn**
- `broad-except` — `except Exception:`, `except BaseException:`, `except (Exception, ...)` → **warn**
- `specific-except-broad-multi` — 여러 개의 specific 예외 catch (`except (OSError, IOError, ValueError):`) → **info** (판단 회색지대)
- `specific-except` — 단일 specific 예외 catch → **info**

+ dup.block v5와 같은 path filter (`tests/`, `examples/`, `docs/`, `scripts/`) → 해당 경로의 warn을 info로 강등

**예상 v2 효과:**
- tests/data/ 34개 → info (경로 필터)
- 나머지 boilerplate 54개 중 대부분 specific-except → info
- warn 남는 것: 주로 broad exception (~10-15개), 그 중 5-6개 tp
- actionable 예상: **~35-50%**

## v2 리스크

- broad exception이 항상 나쁜 건 아님: 최상위 main()에서 `except Exception:` + 로그는 정당. `except Exception:` 다음에 로그나 re-raise가 있는지 봐야 완벽. 하지만 v2는 body가 `pass`/`...`인 경우만 flag하므로 로깅 있는 케이스는 이미 제외됨.
- `except Exception as e: logger.warning(e)`는 이미 제외 대상. 이건 안전.

## 판단 필요

1. **error-masking v2 착수 여부** — 단순한 재분류이므로 v3~v5 dup.block 튜닝보다 훨씬 안전. 1시간 미만 예상. 추천
2. v2 후 재라벨링 필요 여부 — v1 표본에서 filtered rows 제외하고 재계산하면 대부분 커버 가능
3. Week 4 원래 계획 병행 여부 (`--exit-code`, GitHub Action)
