# P0 파일럿 — test.mocks-target v1 결과

날짜: 2026-09-10
표본: 10 저장소 (bench/clones), 총 20 findings

## 구현

`test_x.py` → 대응 target 파일 `x.py` 매핑 (naming convention + shared-prefix + shortest-path 해석). Target 파일의 top-level function/class 심볼 수집. 테스트 함수 안에서 `patch("...")` / `mocker.patch("...")` / `patch.object(mod, "X")` 호출 감지, patch 대상의 마지막 세그먼트가 target 심볼과 일치하면 flag.

## 실측

| 저장소 | findings |
|---|---:|
| aiohttp | 18 |
| poetry | 1 |
| pytest | 1 |
| 나머지 7 | 0 |
| **합계** | **20** |

## 정밀도 판정 (20건 전량 수동 검증)

| 패턴 | 개수 | 판정 |
|---|---:|---|
| **표준 라이브러리 이름 충돌** (fp) | 1 | pytest `test_scandir_handles_os_error` — target `pathlib.py`에 `scandir` 함수 존재. 테스트는 `os.scandir`를 patch (stdlib). 같은 짧은 이름, 다른 심볼 → 분석기 혼동 |
| **동일 모듈 내 helper mocking** (fp) | 17 | aiohttp 전부. `TCPConnector` 클래스 메서드를 테스트하면서 같은 모듈의 `create_connection` / `start_tls` 헬퍼를 mock. 테스트는 실제로 target을 테스트하고 있음, mock한 것은 dependency |
| **호출 추적 테스트** (style/borderline) | 1 | poetry `test_info_from_poetry_directory_fallback_on_poetry_create_error` — 여러 함수를 patch해서 orchestration 검증 (call_count assertion). 판정 여지 있음 |
| **진짜 tp** | 0 | 없음 |

**정밀도: 0/20 = 0% (엄격) 또는 1/20 = 5% (관대)**

## BRIEF §13.5 중단 기준 대비

인용: "관계 판정의 수동 검증 정밀도가 낮으면(예: 0.7 미만) → 지표에서 제외하고 남은 항목으로 축소"

**0% ≪ 70%. 명시적 중단 기준 발동.**

## 근본 원인 분석 (BRIEF §13.3에서 예고된 것)

핵심 문제는 **target = 파일이 아니라 심볼(클래스/함수)이라는 것**. 분석기는 `test_x.py` → `x.py` 매핑하고 그 파일의 모든 top-level 심볼을 "target"으로 취급. 하지만:

- 대부분의 테스트는 target 파일 안의 **하나의 클래스/함수**를 검증
- 같은 파일의 다른 심볼은 그 클래스의 **dependency**
- Dependency를 mock하는 것은 정당한 unit test 관례

예: `test_connector.py::test_tcp_connector_certificate_error`
- 실제 SUT (Subject Under Test): `TCPConnector` 클래스
- Mock 대상: `create_connection` (같은 모듈의 helper function)
- 이건 SUT의 dependency를 mock하는 것. **완벽하게 정당**.

## v2로 정밀도를 올리려면?

SUT (Subject Under Test) 감지 필요:
1. 테스트 함수 안에서 생성자 호출 (`TCPConnector(...)`) 감지
2. 그 인스턴스에 호출된 메서드 (`conn.connect(...)`) 추적
3. SUT = {생성한 클래스, 호출한 메서드/함수}
4. Mock 대상이 SUT set에 없으면 → fp (dependency mock)
5. Mock 대상이 SUT set에 있으면 → tp (진짜 target mocking)

**작업량 예상**: 최소 3-5일. 여러 test 파일 패턴 검증 필요. 정밀도 여전히 0.7 도달 보장 없음.

## BRIEF §12.4 vs §13.6 원칙 적용

- §12.4: "논문 때문에 제품을 비틀지 않는다"
- §13.6: "P0~P1은 버려지는 작업이 아니다. 파일럿에서 만드는 지표 v0가 곧 M2의 `test.authenticity` 분석기"

현 상황:
- v1 지표는 사용 불가 (fp 지배)
- v2 구현은 최소 1주 소요 + 정밀도 불확실
- 이 상태에서 뮤테이션 상관 측정은 무의미 (지표 자체가 unreliable)

## 판단 필요

### 옵션 A — v2 SUT 감지 구현 (1주+)
- 성공 시: 관계 판정 정밀도 0.7 달성 가능 → 뮤테이션 상관 측정 → 논문 A 정상 진행
- 실패 시: 또 1주 낭비 후 여전히 중단

### 옵션 B — BRIEF §13.5 준수, mocks-target 지표에서 제외
- test.authenticity 지표를 다음으로 재정의:
  - `assertion-free` (이미 v1 있음) — 정밀도 미측정, 라벨링 필요
  - `always-true-assertion` — `assert True`, `assert x == x` 등 (신규, 하루)
  - `no-test-for-public-symbol` — 새 public 함수/클래스에 대응 테스트 없음 (신규, 이틀)
- 논문 A: RQ1/RQ2는 SUT 없이도 수행 가능 (지표 v0 있으면 됨). RQ3만 포기
- 뮤테이션 상관 측정 진행 가능

### 옵션 C — 논문 A 중단, 논문 C로 전환 (BRIEF §12.2)
- 논문 C: "커밋 시점 유지보수성 게이트가 이후 재작업을 예측하는가"
- 데이터: git 이력만 필요, 뮤테이션 불필요
- 이미 dup.block · error-masking에서 얻은 지표 재활용 가능
- 실행 가능성 가장 높음 (BRIEF §12.2에서 이미 "학부 수준에서 가장 현실적")

## Ponytail 추천: 옵션 B

이유:
- 옵션 A는 §13.5 stop criterion 무시 + 성공 보장 없음
- 옵션 C는 논문 방향 변경, 대안이긴 하나 지금 결정할 필요 없음
- 옵션 B는 §13.5를 그대로 준수, test.authenticity의 다른 축을 살림, 뮤테이션 상관 측정으로 진행 가능
- 만약 옵션 B에서도 상관이 안 나오면 → 그때 옵션 C로 자연스러운 pivot

## 다음 스텝 (옵션 B 채택 시)

1. `test.mocks-target` 분석기를 비활성화 (또는 severity 강등 + label "experimental")
2. `test.always-true-assertion` 구현 (하루)
3. `test.no-test-for-public-symbol` 구현 (이틀) — 이건 test 파일 없이 src만 봐도 계산 가능
4. `test.assertion-free` v2 (경로 필터, broadness 준용) — dup.block v5 원칙 재사용
5. 세 지표 조합 → 뮤테이션 상관 측정 준비
