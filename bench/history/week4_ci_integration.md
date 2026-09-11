# Week 4 — CI 통합

날짜: 2026-09-10

## 산출물

### 1. `cockpit check --exit-code [--exit-at {info,warn,block}]`
- CI에서 findings 발견 시 non-zero exit
- 기본 threshold: `warn`. `--exit-at block`은 block만 실패, `--exit-at info`는 모든 finding에 실패
- Ponytail: severity 순서 하드코딩 (info=0, warn=1, block=2). 임계값 몇 개 안 되므로 config 파일 불필요

### 2. `cockpit baseline save` / `cockpit check --baseline`
- 스냅샷: `.cockpit/baseline.json` (findings id 집합)
- 새 finding만 검사: `check --baseline`이 baseline에 있는 id 제외
- PLAN §9.3 원칙 그대로: "기존 레포에 처음 돌리면 findings가 수천 개다. 스냅샷하고 신규만 보여주지 못하면 아무도 CI에 안 넣는다"

### 3. GitHub Actions workflow
- `.github/workflows/cockpit.yml`
- pip install cockpit → `cockpit check --baseline` → JSON 아티팩트 업로드 → PR 코멘트 (상위 20건)
- `--exit-code`로 새 warn 있으면 job fail

## 발견한 버그 (Week 4에서 고침)

**dup.block의 `window_hash`가 Python `hash()` 사용 → 프로세스마다 달라짐 → Finding id 불안정 → baseline 완전 무효.**

- 원인: Python의 built-in `hash()`는 PYTHONHASHSEED에 따라 랜덤화 (문자열 대상). 프로세스 재시작마다 다른 해시.
- 영향: `baseline save` 후 `check --baseline` 다시 실행하면 같은 finding이 새 것으로 잡힘.
- 수정: `_stable_hash(text)` = `blake2b(text, 4 bytes).hexdigest()`. 결정론적.
- Verify: records 15 findings 저장 → `check --baseline` → 0 새 findings, exit 0 ✓

이 버그는 v3~v5 시절에는 감춰져 있었음 — baseline이 아직 없었기 때문. CI 통합할 때 반드시 발견됨. **PLAN §9.4 결정론 원칙과 정면 충돌하는 버그였음.**

## 스킵한 것 (YAGNI)

- **설정 파일 (`.cockpit.toml`)** — `--exit-at`와 `--baseline`으로 CI 요구 대부분 커버. Analyzer enable/disable는 요청 오면 추가
- **`baseline update` / `baseline diff`** — save + 재실행이면 충분. 세밀한 diff는 요청 오면 추가
- **PR 코멘트에 evidence 링크** — GitHub 코멘트에 파일:줄 링크가 이미 clickable

## 자체 dogfooding

```
cockpit check --exit-code           # exit 1 (warn 존재)
cockpit check --exit-code --exit-at block  # exit 0 (block 없음)
cockpit baseline save               # 현재 상태 저장
cockpit check --exit-code --baseline # exit 0 (모두 baselined)
```

## 남은 것

Week 5: P0 파일럿 (BRIEF §13.4). dup.block v6 옵션 (관계 판정) 여기서 겹침.

Week 4 원래 계획 vs 실제:
- ✅ 임계값 조정 (dup.block v4/v5, error-masking v2)
- ✅ `--exit-code`
- ⏭ 설정 파일 (스킵, YAGNI)
- ✅ GitHub Action + PR 코멘트
- ✅ + baseline (계획에는 M2로 되어 있었으나 CI 통합에 필수라 앞당김)
- ✅ + id stability fix (버그 발견)

## 판단 필요

1. Week 4 완료 인정 → Week 5 진행 (P0 파일럿)
2. 릴리즈 준비 (README, pypi 등록 등) 병행 여부
3. 실제 GitHub Actions 검증 (원격 저장소 필요) 언제 할지
