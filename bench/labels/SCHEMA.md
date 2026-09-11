# Labeling schema

## 라벨 태그 (5종)

| 태그 | 정의 | 예시 |
|---|---|---|
| `tp` | 진짜 문제. 리뷰어라면 지적하거나 고칠 것 | 실제 로직 복붙, `except: pass`로 삼켜지는 IO error |
| `fp` | 오탐. 분석기가 틀림 | `except: pass`가 의도된 스킵(`__all__` probe 등), decorator 반복 |
| `boilerplate` | 기술적으로 중복이지만 자연스러움, 리팩터링 강요하면 오히려 나빠짐 | 테스트 setup, dataclass field stubs, 스키마 정의 |
| `style` | 진짜지만 사소함 (경고할 가치 없음) | 3-4줄짜리 minor helper 반복 |
| `unclear` | 판단 보류. 문맥 필요 | 라이브러리 규약, 도메인 지식 필요 |

## 지표 정의

라벨링된 표본을 기준으로:

- **정밀도(precision)** = tp / (tp + fp + style)
  - `boilerplate`는 별도 취급 — 노이즈지만 오탐은 아님
- **actionable 정밀도** = tp / total
  - 사용자 관점의 "이거 볼만한가" 비율
- **회수율(recall)** = 별도 실험 필요 (기지의 결함 데이터셋 대조)

## 게이트 통과 기준 (PLAN §4)

| 지표 | 통과선 | 조치 |
|---|---|---|
| tp 비율 | ≥40% | Week 4 진행 |
| tp 비율 | 20~40% | 임계값 재설계에 Week 4 소진 |
| tp 비율 | <20% | 분석기 재설계 |

## 워크플로우

1. `python bench/label.py sample dup.block` → 층화 표본 CSV 생성
2. 사람이 CSV `label` 컬럼 채움 (위 5종 중 하나)
3. `python bench/label.py score dup.block` → 지표 계산 + 저장
4. 결과 `bench/labels/scores/<analyzer>_<date>.md`에 남김

## 파일 규칙

```
bench/labels/
  SCHEMA.md                        # 이 파일
  samples/
    <analyzer>_<date>.csv          # 층화 표본 (label 컬럼 비어있음)
  labeled/
    <analyzer>_<date>.csv          # 라벨링 완료
  scores/
    <analyzer>_<date>.md           # 계산된 지표 + 원인 요약
```
