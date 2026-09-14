# cockpit

> AI가 짠 코드를 개발자가 직접 검증하기 쉽게 만드는 로컬 도구.
> **판정은 AST·그래프·해시 기반 결정론적 계산으로만 한다. 분석 경로에 LLM 호출이 없다.**

pre-release · Python 3.11+ · MIT

```bash
pip install cockpit-review     # 배포판 (릴리즈 후)
# 또는 소스에서: pip install -e .
cockpit check                  # 현재 디렉토리를 분석
cockpit check --json           # 스키마 v1 envelope 출력
```

PyPI 패키지명은 `cockpit-review` (이름 충돌 회피), CLI 명령은 `cockpit`.
Source: https://github.com/sozerong/cockpit-review

## 왜 있는 게 아니라 왜 있는가

CodeRabbit, Greptile, Qodo, BugBot — 지금 시장의 AI 코드 리뷰 도구는 전부 LLM
기반이다. 결과가 비쌈·느림·비결정론·같은 종류로 검증. cockpit은 그 고리 밖에
서 있다: **사람이 판정 주체이고, 기계는 근거만 수집한다.** 모든 finding은 클릭
가능한 evidence를 붙인다.

전체 설계 근거는 [PROJECT_BRIEF.md](PROJECT_BRIEF.md), 6주 실행 계획은
[EXECUTION_PLAN.md](EXECUTION_PLAN.md), 각 분석기 튜닝 이력은
[bench/history/](bench/history/).

## 명령어

```bash
cockpit check [repo]                # 분석 + 터미널 표
cockpit check --json                # JSON envelope (스키마 v1)
cockpit check --exit-code           # warn 이상 있으면 exit 1 (CI용)
cockpit check --exit-at info        # info 이상에서도 실패
cockpit check --baseline            # baseline에 있는 finding 제외

cockpit baseline save               # 현재 findings 스냅샷 (.cockpit/baseline.json)

cockpit watch [repo]                # 파일 변경 시 재실행, NDJSON 스트림
cockpit watch --once                # 한 번만 emit

cockpit report [repo] [--out FILE]  # 단일 파일 HTML 리포트 생성
                                    # 기본 경로: <repo>/cockpit-report.html
```

`report`는 findings JSON을 임베드한 자립형 HTML을 만든다. 브라우저에서 열면
severity 필터, 텍스트 검색, evidence 클릭 확장 — CDN·번들러 없음, 파일 하나로 완결.

## 분석기 (v0.0.1 시점)

라벨링 기반 튜닝 결과. 자세한 실측·근거는 `bench/history/<analyzer>_v<N>.md`.

| 분석기 | severity | 실측 정밀도 (100건 라벨) | 상태 |
|---|---|---:|---|
| `risk.error-masking` | warn / info | **50%** (broad-except) | PASS |
| `dup.block` | warn / info | 28% (2-5회 클러스터) | 부분 통과 |
| `test.assertion-free` | info | 4% (helper wrapper 감지 못함) | info 강등 |
| `test.always-true-assertion` | info | 14% (n=7) | info 강등 |
| `test.no-test-for-public-symbol` | info | 12% | info 강등 |

**severity 계층:**
- `warn` — 리뷰어가 실제로 봐야 하는 것
- `info` — 신호는 있지만 정밀도가 낮아 CI 실패 유발 안 함
- `block` — (미사용) 명확한 결함

## GitHub Actions

`.github/workflows/cockpit.yml` 예시 포함. `pip install .` → `cockpit check
--baseline` → PR에 findings 코멘트. baseline은 저장소 `.cockpit/baseline.json`에
스냅샷.

## 저장소 구조

```
src/cockpit/                # 분석 엔진, CLI, watch, baseline
bench/                      # 게이트 실측 · 라벨링
  run.py                    # 10 저장소 · 튜닝 실측
  label.py                  # 층화 표본 · 채점
  history/                  # 각 분석기 버전별 실측 근거
  labels/                   # 라벨링된 CSV + 지표
  paper_c/                  # 유지보수성 지표의 재해석 논문 파일럿
.github/workflows/          # CI 예시
```

## 언어 지원

Python 먼저. TypeScript는 dup.block v6 이후. tree-sitter라서 확장은 문법 추가만.

## 상태

Week 4 CI 통합 완료, Week 5 P0 파일럿에서 test.authenticity 3종 §13.5 stop 발동
→ info 강등. Week 6 Paper C 확장 실측 중. 자세한 로드맵은
[EXECUTION_PLAN.md](EXECUTION_PLAN.md) §2.
