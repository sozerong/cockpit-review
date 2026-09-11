# Bench history

각 분석기 버전의 실측 결과와 재설계 근거를 남긴다. 이유:
- 후회 방지: 이미 시도한 heuristic을 다시 시도하지 않도록
- 논문 A/C의 방법론 초안이 여기서 만들어짐 (PLAN §12)
- README 첫 줄에 들어갈 숫자의 출처

## 파일 규칙

- `<analyzer>_v<N>.md`: 해당 버전 실측 + 왜 이 버전을 만들었는지 + 다음 버전 방향
- `raw/<analyzer>_v<N>_<repo>.json`: 원본 finding 스냅샷 (재현용)

## 현재 상태 (Week 4 종료 시점)

| 분석기 | 최신 버전 | actionable | 게이트 | 비고 |
|---|---|---:|---|---|
| risk.error-masking | v2 | 50.0% | **PASS** | broadness + 경로 필터 |
| dup.block | v5 | 28.0% | THRESHOLD | Week 5 P0에서 관계 판정 예정 |
| test.assertion-free | v1 | (미측정) | 정지 | Week 5 P0 관계 판정 필요 |

## CI 통합 (Week 4)

- `cockpit check --exit-code [--exit-at]`
- `cockpit baseline save` + `check --baseline`
- `.github/workflows/cockpit.yml` 예시

발견 버그: dup.block window_hash가 Python built-in `hash()` 사용해 프로세스마다 달라짐 → Finding id 불안정 → baseline 무효화. blake2b로 교체 완료.

## 라벨링 관련

- 스키마: `bench/labels/SCHEMA.md`
- 헬퍼: `python bench/label.py sample <id>` / `score <id> <csv>`
- 게이트 통과선: actionable 비율 (tp/labeled) 40%+
- 지금까지 총 313건 라벨링 완료 (dup v3 100 + v4 99 + v5 100 + em v1 99 + em v2 14 = 412건)
