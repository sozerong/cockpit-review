# Paper C 방향 전환 — "예측 논문"에서 "재해석 논문"으로

날짜: 2026-09-10
근거: 4 저장소 파일럿 결과 (Paper_C_v1)

## 원 방향 (폐기)

**RQ (원):** 커밋 시점의 유지보수성 지표 (dup.block, error-masking warn 밀도)가
이후 파일 재작업(14일 churn)을 **예측하는가**?

**동기:** GitClear "Maintainability Gap" 저자들이 상관 관찰만 하고 인과 주장은
피했음. 커밋 시점 예측력을 통해 인과 방향의 첫 검증.

## 파일럿에서 벌어진 일

- 4 저장소, 400 커밋, 4,379 rows
- 원 가설의 반대 방향으로 상관 나옴: ρ_dup = **-0.36** (CI 0 배제)
- 4 저장소 모두 방향 일관 → 우연 아님
- Baseline (loc) 상관보다 훨씬 큼 → 크기 대리 지표 아님

## 새 방향

**RQ (신):** 코드 유지보수성 지표는 **예측 도구가 아니라 age/stability 프록시**인가?
**즉, "코드가 오래됐고 아무도 안 건드리는가" 를 재는 지표인가?**

### 하위 RQ

- **RQ-A**: warns 밀도와 파일 age 간의 상관은 얼마인가? (양수·유의미할 것 예상)
- **RQ-B**: age를 통제한 후 warns가 churn을 예측하는가? (부호 유지될 것 예상 = 여전히 음수 or 0으로 수렴)
- **RQ-C**: warns가 높으면서도 churn이 높은 파일이 있는가? 있다면 그것이 진짜 "위험한 파일" 아닌가?

### 논문 기여

1. **GitClear류 상관 연구의 인과 착각 명시적 반증**
   - dup·error-masking 증가 = 유지보수성 악화라는 해석의 재고
   - "많은 warns"는 코드가 오래됐다는 신호일 뿐, "고쳐야 한다"는 신호가 아님
2. **유지보수성 지표의 실용 재정의**
   - 개발자 관점: warns 많음 = "이 코드는 성숙 utility, 함부로 리팩터링 하지 말 것"
   - AI 에이전트 관점: warns가 급증한 신규 파일 = 진짜 위험 신호 (age 낮은데 warns 높음)
3. **cockpit의 도구 정당화 재기술**
   - 원래: "AI가 만든 잠재적 문제를 감지"
   - 신: "AI가 만든 신규 코드에서 성숙 utility 코드의 패턴이 반복되는지를 감지"
   - RQ-C의 발견 (young + warns↑) 이 cockpit의 핵심 알림 대상

## 방법론 변경

기존 harness/analyze로 부족한 것 → 필요한 추가 데이터:
- ✅ 파일 first-commit-date (age_days) — analyze.py v2에서 추가
- 파일 최근 활동 지표 (지난 30일 커밋 수) — 미구현
- 파일 유형 (src/test/other) — 이미 필터

기존 harness/analyze 재활용 가능한 것:
- (repo, sha, file, loc, warns_dup, warns_em, churn_14d) — 그대로
- Bootstrapped Spearman CI — 그대로
- 저장소 fixed effects — 저장소별 결과로 이미 다뤄짐

## 파일럿 → 확장 계획

**Phase 1 (진행 중, 오늘 마감):** 남은 6 저장소 harness 실행 → 총 10 저장소, 1000 커밋

**Phase 2 (age 통합):** analyze.py v2 실행 → H1 (원가설) + H2 (재해석) 지표 동시 산출

**Phase 3 (partial correlation):** age를 통제한 warns~churn 상관. numpy 도입할 수도 (`np.corrcoef` on residuals). Ponytail: 필요 시.

**Phase 4 (원고 초안):** 만약 H2가 유의하게 강하면 논문 초안 작성. 대상: MSR (§BRIEF 12.3).

## BRIEF §12.4 원칙 재확인

> 논문 때문에 제품을 비틀지 않는다.

- 지금 방향 전환은 **논문이 제품 데이터를 따라가는** 케이스, 반대가 아님
- 데이터가 새 방향을 강력히 시사 → 그 방향으로 프레이밍 조정
- 제품 (cockpit) 자체는 코드 변경 없음
- 다만 README 도구 소개 문구는 이 결과 나온 뒤 조정 가능 ("stability proxy" 언급 여부)

## 상태

- ✅ 방향 전환 공식화 (이 문서)
- 🕐 Phase 1: aiohttp/black 완료, fastapi/pytest/poetry/flask 진행 중 (6 of 10)
- ✅ Phase 2: analyze.py v2 (age 컬럼 추가)
- ✅ Phase 3: partial correlation 구현 완료, 6-repo 잠정 결과 나옴
- ⏳ Phase 4: 논문 초안 (Phase 1 완료 후)

## Phase 3 잠정 결과 (n=8094, 6 repos)

| 가설 | 지표 | ρ | 95% CI |
|---|---|---:|---|
| H1 예측력 | dup → churn | -0.357 | [-0.379, -0.335] |
| H1 예측력 | em → churn | -0.140 | [-0.162, -0.119] |
| H2 age 프록시 | dup → age | +0.275 | [+0.255, +0.295] |
| H2 age 프록시 | em → age | +0.151 | [+0.132, +0.172] |
| H2 age 프록시 | loc → age (기저) | +0.431 | — |
| **H3 partial** | dup → churn \| age | **-0.303** | [-0.328, -0.281] |
| **H3 partial** | em → churn \| age | -0.103 | [-0.124, -0.083] |

## H3 발견 — 재해석 가설도 부분 반증

**만약 warns가 순수 age 프록시라면**: age를 통제하면 warns의 상관이 0에 수렴해야 함.

**실제 관찰**: partial ρ가 -0.357 → -0.303. **86% 유지됨.**

즉:
- age는 warns 신호의 **일부만 설명** (약 15% 감소)
- **warns 자체가 "무엇인가"를 신호함** — 그 무엇인가는 age가 아님
- 첫 후보: **파일의 "책임 안정성"** — utility 성 helper 코드는 age에 무관하게
  중복이 잘 생기고, 그런 파일은 churn이 낮음. 즉 warns는 "이 파일은
  helper/utility 계열이다"를 신호함
- 두 번째 후보: **파일의 "규모"** — 하지만 loc partial 통제 없이 봐도 loc→age
  상관(+0.43)이 warns→age(+0.28)보다 강함. 다변량 통제 필요 (Phase 3.5)

## 논문 재프레이밍 (H3 반영)

새 논문 골격:
1. **관찰**: cockpit-style warns가 이후 churn을 **역상관**으로 예측 (강한 신호)
2. **가설 1 (age)**: warns는 age 프록시 → 부분 지지 (ρ=+0.275) 하지만 완전하지 않음
3. **가설 2 (stability)**: warns는 파일의 stability를 신호 (age와 무관하게)
   - age 통제 partial 상관이 여전히 강함 → 이 가설 지지
4. **함의**: 
   - GitClear류 "유지보수성 저하" 해석은 잘못됨
   - warns 지표는 리팩터링 요구가 아니라 **파일 성격 판별**에 유용
   - AI 코드에서 신규 파일에 warns 급증은 **성숙 helper 패턴이 신규 코드에 조기 등장**을 의미 (이게 cockpit의 원래 alert 대상)

## Phase 3.5 후속 (다변량 통제)

age 하나만 통제는 부족. 필요한 partial:
- ρ(warns, churn | age, loc) — 크기·나이 둘 다 통제 후 순수 warns 효과
- ρ(warns, churn | age, loc, active_30d) — 최근 활동 통제

이 계산은 partial 공식 재귀 적용 or numpy 도입 필요. Phase 1 완료 후 판단.

## 확대 실측 후 재판정 기준

| 결과 | 조치 |
|---|---|
| H1 음의 상관 유지 + H2 양의 상관 유의 | **논문 초안 착수** — GitClear 반박 + age 프록시 재해석 |
| H1 결과 뒤집힘 (양수로) | 원 예측 가설로 회귀, GitClear 지지 방향 |
| H1·H2 둘 다 무의미 | 논문 C 완전 폐기, product-only로 |
| 저장소별 분산 큼 (heterogeneity) | 하위 그룹 분석 후 부분 논문 |
