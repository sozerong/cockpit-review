# v0.1.0 release runbook

## A. PyPI upload (Windows PowerShell)

Built artifacts (v0.2.0): `C:\Users\dudfo\AppData\Local\Temp\cockpit_dist_v020\cockpit_review-0.2.0*`

```powershell
# 1. Isolated venv for twine
py -3.11 -m venv .venv-publish
.\.venv-publish\Scripts\Activate.ps1
python -m pip install --upgrade pip twine

# 2. Sanity-check artifacts
twine check C:\Users\dudfo\AppData\Local\Temp\cockpit_dist_v020\cockpit_review-0.2.0*

# 3. One-time token setup — edit %USERPROFILE%\.pypirc
#    TestPyPI token: https://test.pypi.org/manage/account/token/
#    PyPI token:     https://pypi.org/manage/account/token/
notepad $env:USERPROFILE\.pypirc
```

`.pypirc`:

```
[distutils]
index-servers = pypi testpypi

[pypi]
username = __token__
password = pypi-...

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-...
```

```powershell
# 4. TestPyPI dry run
twine upload -r testpypi C:\Users\dudfo\AppData\Local\Temp\cockpit_dist_v020\cockpit_review-0.2.0*

# 5. Verify from TestPyPI in a clean venv
py -3.11 -m venv .venv-verify
.\.venv-verify\Scripts\Activate.ps1
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cockpit-review==0.2.0
cockpit --version
deactivate

# 6. Real PyPI
twine upload C:\Users\dudfo\AppData\Local\Temp\cockpit_dist_v020\cockpit_review-0.2.0*

# 7. Post-verify
py -3.11 -m venv .venv-final
.\.venv-final\Scripts\Activate.ps1
pip install cockpit-review
cockpit check --help
```

**Name taken?** 403 "File already exists" (same name+version) or 400 "not allowed to upload". Rename in `pyproject.toml`, bump to `0.1.1`, `python -m build`, retry from step 2.

## B. GitHub Release body (paste into tag v0.1.0)

See `RELEASE_NOTES.md`.
