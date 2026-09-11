# Paper C — 커밋 시점 유지보수성 지표의 재작업 예측력

BRIEF §12.2의 논문 후보 C. Ponytail 진입점.

## 배경

GitClear "Maintainability Gap" (2026)는 dup·churn·error-masking 지표와 AI 코드
증가의 **상관**을 보였음. 저자들 스스로 "이건 상관이지 인과가 아니다"라고
명시. **미해결 문제:** 커밋 시점 지표가 **이후 재작업**을 예측하는가?

## RQ

- **RQ1**: 커밋 X 시점의 `dup.block` warn 밀도(=파일당 warn 수)가 커밋 X+14일 시점의
  파일 churn(재작업 라인 %)을 예측하는가?
- **RQ2**: `risk.error-masking` warn 밀도도 예측하는가?
- **RQ3**: 두 지표 조합이 각각보다 예측력이 나은가?

## 지표 정의

### X (예측변수, 커밋 시점 t)

파일별:
- `warns_dup(t, f)` = cockpit dup.block warn 개수 in file f
- `warns_em(t, f)` = cockpit risk.error-masking warn 개수 in file f
- `loc(t, f)` = 파일 라인 수 (정규화)

### Y (결과변수, 14일 후)

- `churn_14d(t, f)` = git log 로 계산한 f에 대한 insertions+deletions 합 (t ~ t+14d)
- 정규화: `churn_ratio_14d(t, f) = churn_14d / loc(t, f)`

## 표본 설계

- 저장소: 10 (기존 bench/clones/*)
- 각 저장소에서 무작위 커밋 100개 샘플링 (main 브랜치 한정)
  - 조건: `commit_date + 14d < now`
  - 조건: main 이력에 도달 가능한 커밋 (fork/branch만 있는 것 제외)
- 커밋당 인덱싱된 각 .py 파일 → 1 row
- 예상 총 rows: 10 × 100 × (평균 파일 수 ~100) = ~100,000 (파일 필터 후 훨씬 적음)

## 공변량 (분석 전 확정)

- 파일 크기 (LOC)
- 파일 age (첫 커밋부터 t까지)
- 저장소 (10 fixed effects)
- 파일 타입 (src / test / other)
- 커밋 authoring density (해당 파일 최근 30일 커밋 수)

## 분석

- Poisson regression (churn = count) with log(loc) offset
- OR log-linear: `log(churn+1) ~ log(warns+1) + covariates + repo_fe`
- Bootstrapped 95% CI for coefficient
- Robustness: alternative churn window (7d, 30d)

## 중단 기준

- warns 계수의 95% CI가 0을 포함하면 → 유의성 없음, 논문 A 시나리오와 동일하게 중단 판단
- 계수는 유의하지만 부호가 예상과 반대 (warns 많음 → churn 적음) → 재해석 필요

## 파이프라인

```
bench/paper_c/
  PLAN.md                  # 이 파일
  harness.py               # 무작위 커밋 표본 → cockpit + git churn → CSV
  analyze.py               # CSV → 회귀 + 그림
  out/
    <repo>_samples.csv     # commit_sha, date, file, warns_dup, warns_em, loc, churn_14d, ...
    combined.csv           # 전 저장소 합본
    report.md              # 계수, CI, 그림
```

## Ponytail 실행 순서

**MVP (1일):** 1 저장소(records), 20 커밋 파일럿. 파이프라인이 도는지 확인.
- git checkout at each commit → cockpit --json → 파일별 warn 카운트
- git log 로 각 파일의 churn 계산 (t ~ t+14d)
- 파일별 (warns, churn) tuple 저장

**Scale (3-5일):** 10 저장소, 100 커밋 each. combined.csv 생성 → 회귀.

**Analysis (2일):** 회귀 + 그림 + 초안 report.md.

## 리스크

1. **cockpit이 checkout 별로 도는 데 시간 오래 걸림** — 100 커밋 × 15초 = 25분/repo. 감내 가능. 병렬화는 나중에.
2. **Git checkout이 shallow clone에서 실패** — 필요 시 `git fetch --unshallow`.
3. **파일 rename 추적** — `git log --follow` 사용해야 정확한 churn. 놓치면 churn 저평가.
4. **v5 dup.block과 v2 error-masking의 안정성** — v5, v2 확정된 상태. 안전.

## 대안 데이터 (더 lazy)

과거 커밋 대신 최근 릴리즈들 사이의 diff를 사용:
- 각 릴리즈 태그에서 cockpit check
- 다음 릴리즈까지의 churn을 그 창구로 사용
- checkout 대신 태그 diff → 훨씬 빠름

하지만 릴리즈 간격이 저장소마다 크게 달라서 통제가 어려움. 우선 무작위 커밋 방식으로 진행.

## 다음 결정 필요

1. MVP 저장소 선택 (records 추천, 파일 9개로 빠름) — 그리고 커밋 수 (20 추천)
2. 실행 시점 — Week 5 잔여 시간 vs Week 6 착수
