# v0.1.0 release checklist

## 완료 상태

- ✅ PyPI 이름: **cockpit-review** (CLI 명령은 `cockpit` 유지)
- ✅ GitHub URL: **github.com/sozerong/cockpit-review**
- ✅ pyproject.toml 이름·URL 반영
- ✅ README.md 배포 안내 갱신
- ✅ .gitignore (bench/clones/, dist/, .cockpit/, ...)
- ✅ git init + first commit `c30683d`
- ✅ git tag `v0.1.0` (annotated)
- ✅ 기본 브랜치 main
- ✅ Remote `origin` → github.com/sozerong/cockpit-review.git
- ✅ dist 리빌드: `/tmp/cockpit_dist/cockpit_review-0.1.0.tar.gz`, `.whl`

## 남은 배포 액션 (사용자 직접)

### 1) GitHub 저장소 생성 + 푸시

github.com/sozerong 계정에서 **빈 저장소 `cockpit-review`** 생성 (README·license 자동
생성 옵션 끔 — 여기 로컬에 이미 있음).

```bash
cd C:/Users/dudfo/Desktop/2026main
git push -u origin main
git push origin v0.1.0
```

인증은 GitHub CLI(`gh auth login`) 또는 personal access token.

### 2) PyPI 업로드

**A. test.pypi 먼저 (권장)**

```bash
python -m pip install --upgrade twine
python -m twine upload --repository testpypi /tmp/cockpit_dist/cockpit_review-0.1.0*
```

test.pypi.org 계정 필요. 업로드 성공하면:
```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cockpit-review
cockpit check --help  # 동작 확인
```

**B. 실 PyPI**

```bash
python -m twine upload /tmp/cockpit_dist/cockpit_review-0.1.0*
```

pypi.org 계정 + 2FA 필요.

### 3) GitHub Release 생성

푸시 후 github.com/sozerong/cockpit-review/releases/new 에서:
- Tag: `v0.1.0`
- Title: `v0.1.0 — first release`
- Body: `CHANGELOG.md` v0.1.0 섹션 붙여넣기
- `/tmp/cockpit_dist/*` 첨부 (또는 PyPI 링크만 남김)

## 잠재 이슈 확인용 명령

```bash
# 태그와 커밋 확인
git log --oneline --decorate
# 빌드 검증
python -m pip install --force-reinstall /tmp/cockpit_dist/cockpit_review-0.1.0-py3-none-any.whl
cockpit check --json bench/clones/records 2>/dev/null | python -c "import json,sys; e=json.load(sys.stdin); print(e['summary'])"
```

## 로컬 상태

- 커밋 `c30683d`, 태그 `v0.1.0`, 85 파일, `bench/clones/` 제외
- Remote 설정만 완료, **아직 push 안 함**
- PyPI 등록 안 함 (사용자 계정·2FA 필요)

## 배포 후 후속 (선택)

- README에 PyPI 배지, GitHub Actions 배지 추가
- `bench/paper_c/draft/` 초안 계속 (§5–§7)
- 사용자 피드백 대응
