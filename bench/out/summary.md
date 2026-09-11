# Week 3 Gate — Overlap Report

Repos analyzed: 10 / 10
Total files scanned: 2653
Ruff rules compared: `BLE001,S110,E722,PIE790`
Tolerance: ±3 lines

## Error-masking overlap

| | Count |
|---|---|
| cockpit `risk.error-masking` total | 243 |
| ruff hits (all files) | 561 |
| **overlap** (same file:line ±3) | 52 (21.4%) |
| **unique to cockpit** | 191 (78.6%) |

## Per repo (all analyzers)

| repo | files | em (cockpit) | em (ruff) | overlap | em unique | dup.block | assertion-free |
|---|---:|---:|---:|---:|---:|---:|---:|
| requests | 37 | 9 | 1 | 0 | 9 | 87 | 10 |
| click | 90 | 16 | 27 | 7 | 9 | 212 | 10 |
| flask | 83 | 9 | 17 | 7 | 2 | 149 | 12 |
| black | 343 | 124 | 449 | 25 | 99 | 439 | 38 |
| fastapi | 1138 | 8 | 13 | 5 | 3 | 3288 | 15 |
| pytest | 274 | 51 | 46 | 7 | 44 | 1349 | 531 |
| poetry | 447 | 5 | 5 | 1 | 4 | 1692 | 140 |
| httpx | 60 | 3 | 2 | 0 | 3 | 408 | 2 |
| aiohttp | 172 | 17 | 0 | 0 | 17 | 2614 | 76 |
| records | 9 | 1 | 1 | 0 | 1 | 2 | 12 |
