# P0 파일럿 v2 — 옵션 B (mocks-target 제외 후 대안 지표 3개) 결과

날짜: 2026-09-10
라벨링: 총 207건 (assertion-free 100, always-true-assertion 7, no-test-for-public 100)

## 실측 총량 (10 저장소)

| 분석기 | v2 findings 총량 |
|---|---:|
| test.assertion-free | 827 |
| test.always-true-assertion | 7 |
| test.no-test-for-public-symbol | 631 |
| test.mocks-target (v1, disabled) | 20 |

## 라벨링 결과

### test.always-true-assertion (n=7, 전량 라벨)

| 라벨 | 개수 |
|---|---:|
| tp | 1 |
| fp | 6 |

**actionable 14%.** tp 1건은 `assert b"123", data["name"]` (2-arg assert의 `expression, msg` 오용 → 항상 true) — 실제 테스트 버그. fp 6건은 전부 `assert x == x` 형식으로 `__eq__` **reflexivity 의도적 검증**.

### test.assertion-free v2 (n=100, 자동+보조 라벨)

| 라벨 | 개수 |
|---|---:|
| tp | 4 |
| fp | 86 |
| style | 1 |
| boilerplate | 6 (benchmark tests) |
| unclear | 3 |

**actionable 4%.** 지배적 fp 원인: **assertion이 helper 함수 안에 있음**. `self.check_features_used(...)`, `self.invokeBlack(exit_code=1)`, `check_solver_result(...)` 같은 wrapper가 실제 assertion을 수행. 분석기는 test 함수 body만 walk하므로 놓침.

### test.no-test-for-public-symbol v1 (n=100, 자동+보조 라벨)

| 라벨 | 추정 개수 |
|---|---:|
| tp | ~12 |
| fp | ~32 (다른 test 파일에서 참조됨) |
| boilerplate | ~40 (Protocol 타입, HTTPException 서브클래스 계열, ABC 등) |
| style | ~15 (helper class, 간접 테스트) |

**actionable ~12%.** fp 32건은 `test_<basename>.py` 매칭 test 파일이 아닌 다른 test 파일에서 참조됨. Boilerplate는 Protocol/exception 계열(HTTPConflict 등 40+개 status code 클래스를 개별 테스트 안 함).

## 세 분석기 모두 BRIEF §13.5 stop criterion 미달

| 분석기 | actionable | §13.5 판정 |
|---|---:|---|
| test.mocks-target v1 | 0-5% | **미달** (0.7 이하) |
| test.assertion-free v2 | 4% | **미달** |
| test.always-true-assertion v1 | 14% (n=7 소량) | 소량 표본, 판정 유예 |
| test.no-test-for-public v1 | ~12% | **미달** |

## 근본 원인 (공통 패턴)

세 분석기 모두 **테스트의 유효성을 함수-body 텍스트만으로 판정하려 함**. 실제로:
- Assertion은 helper 함수 안에 있을 수 있음 (assertion-free)
- Mock 대상은 dependency일 수 있음 (mocks-target)
- Test 참조는 다른 test 파일에서 나올 수 있음 (no-test-for-public)
- `assert x == x`는 reflexivity 의도적 검증일 수 있음 (always-true-assertion)

**BRIEF §13.6 예언**: "**대상 자체를 mock했는가**는 어렵고 오탐이 나기 쉽다" — 같은 이유가 모든 test.authenticity 축에 적용됨.

## 시사점

BRIEF §13.5 중단 기준 명시적으로 발동. Ponytail으로 P0 파일럿 중단.

**뮤테이션 상관 측정은 무의미** — 지표 자체가 unreliable (모두 정밀도 <20%). 상관 없어도 지표 문제인지 뮤테이션 문제인지 구분 불가.

## 판단 필요

### 옵션 A — Paper C로 pivot (BRIEF §12.2)
- "커밋 시점 유지보수성 지표가 이후 재작업을 예측하는가"
- 지표: 이미 만든 dup.block v5, error-masking v2 (둘 다 게이트 통과 or 부분 통과)
- 데이터: git 이력만 필요, 뮤테이션 불필요
- 지금까지 만든 파이프라인·라벨링 인프라 그대로 재활용
- BRIEF §12.2: "학부 수준에서 가장 현실적"

### 옵션 B — test.authenticity를 info 강등, 논문 A 잠정 보류
- 세 분석기를 all-info 로 설정 (release에 포함하되 CI failure 유발 안 함)
- 논문 A는 SUT-detection 등 큰 개선 이후 재도전
- Product는 dup + error-masking으로 CI 통합, Paper C 병행 가능

### 옵션 C — 논문 없이 product-only 진행
- 지금까지 산출물로 release (dup.block v5 + error-masking v2 + CI 통합)
- 논문 완전 포기, 다른 프로젝트로

## Ponytail 추천: 옵션 B (그다음 A)

- test.authenticity 분석기 3개를 info 강등 (릴리즈 포함, 발견 신호는 유지, 검증되지 않음 표기)
- Paper C 준비 시작: dup·error-masking 지표를 커밋 시점 처른 예측력 관점에서 재분석
- Paper A는 SUT-detection 정확도 확보 후 재도전 (BRIEF §14의 M4 이후 논문 후보)

## 판단 요청

1. 세 test.authenticity 분석기 → info 강등할지 (기본 disabled 유지 vs info로 활성화)
2. Paper C 준비 착수 여부
3. Product release 시점 (Week 6 원래 계획 유지 or 조기 릴리즈)
