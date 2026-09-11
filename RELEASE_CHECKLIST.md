# v0.1.0 release checklist

## Build artifacts (완료)

- ✅ `cockpit-0.1.0-py3-none-any.whl`
- ✅ `cockpit-0.1.0.tar.gz`
- ✅ Wheel install → CLI 동작 확인 (records: 9 files, warn=2, info=18)
- 빌드 경로: `/tmp/cockpit_dist/`

## 확정된 것

- ✅ README.md
- ✅ LICENSE (MIT)
- ✅ CHANGELOG.md v0.1.0
- ✅ pyproject.toml (classifiers, keywords, urls, sdist include list)
- ✅ `src/cockpit/__init__.py` version bump 0.0.1 → 0.1.0
- ✅ `.github/workflows/cockpit.yml`

## 릴리즈 전 사용자 결정 필요

### 1. PyPI 이름 충돌

**`cockpit` 이름은 PyPI에서 이미 사용 중일 가능성 매우 높음.**
(cockpit-project.org 존재, PyPI에 관련 패키지 있음)

옵션:
- **A. 이름 변경.** 후보: `cockpit-review`, `cockpit-cli`, `code-cockpit`, `pilot`, `hangar`
- **B. 조직 fork로 stake.** `cockpit-anthropic` 등 조직 prefix
- **C. 이름 확인 후 available하면 그대로.** `pip search` deprecated이므로
  https://pypi.org/project/cockpit/ 수동 확인 필요

### 2. GitHub 원격 저장소

`pyproject.toml`의 `project.urls`에 `OWNER` placeholder 있음. 실제 원격 정하면
치환 필요:
- github.com/{USER}/cockpit
- 원격 없으면 URL 절 삭제

### 3. First tag

- 로컬 git repo 초기화 안 되어 있음. `git init` 필요.
- 첫 커밋: 전체 스냅샷
- 태그: `v0.1.0`

### 4. PyPI 업로드 (실제 배포)

**Claude가 대신 수행하지 않음** — 외부 서비스 인증·계정 요구. 사용자 직접 진행.

```bash
python -m pip install --upgrade twine
python -m twine upload /tmp/cockpit_dist/*
```

또는 test.pypi.org 먼저:
```bash
python -m twine upload --repository testpypi /tmp/cockpit_dist/*
```

## Ponytail 추천 순서

1. **이름 최종 결정** — 위 옵션 중. Ponytail: `cockpit-cli` 안전
2. **PyPI 사용 가능 확인** — https://pypi.org/project/{name}/ 응답 확인
3. **pyproject.toml `name` + `project.urls.Source` 갱신**
4. **git init + first commit + tag v0.1.0**
5. **test.pypi 업로드 → 검증 → 실제 pypi 업로드**

## 스킵 (YAGNI)

- CI status badge — GitHub 원격 확정 후 추가
- Contributor guide — 첫 외부 기여자 등장 시 추가
- API 문서 자동 생성 — 사용자가 CLI만 쓰므로 필요 없음
- 다국어 README — 원문 한국어, README도 한국어. 영어 필요시 추후 추가

## 잠재 리스크

- **`tree-sitter` 0.26 API 의존:** 마이너 버전 업그레이드 시 `QueryCursor` API 변경 가능. pin 고려 (지금 `>=0.23`은 광범위)
- **Windows PowerShell 실행 미테스트:** 개발은 Windows + Git Bash, CLI 자체는 argparse라 문제 없어야 하나 `--json` 리다이렉트에서 인코딩 이슈 가능. `PYTHONIOENCODING=utf-8` 안내 README에 추가하는 것 고려

## 승인 필요 항목

사용자 확정 후 아래 진행:
- [ ] PyPI 이름 최종 결정
- [ ] GitHub 원격 URL 최종 결정
- [ ] git init + first commit 실행 (Claude 대행 가능)
- [ ] test.pypi upload (사용자 직접)
- [ ] pypi upload (사용자 직접)
