"""`cockpit serve` — live dashboard: file changes → re-scan → browser updates.

Stdlib only. Background thread runs the watch loop (reused from watch.py),
HTTP server exposes:
  GET /            → shell HTML with polling client
  GET /state.json  → current envelope + monotonic version counter

The client polls /state.json?since=<v> and long-waits until a newer version
is ready (up to WAIT_TIMEOUT), then re-renders findings. Poll, not SSE:
http.server has no chunked streaming primitive and long-poll works fine
for a single-user dev-loop dashboard.
"""
from __future__ import annotations
import collections
import datetime
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import baseline as bl
from .incremental import IncrementalScanner
from .watch import _snapshot, POLL_INTERVAL, DEBOUNCE


WAIT_TIMEOUT = 25.0     # long-poll ceiling before returning current state
ACTIVITY_LEN = 12       # rolling scan-event log for the NOW panel


# Per-analyzer rationale shown in the evidence pane. Kept next to the
# analyzer roster so a new analyzer added to __init__.py without a
# rationale here still renders (falls back to the analyzer id).
_RATIONALES = {
    "en": {
        "dup.block":
            "5+ line duplicate windows inside function bodies. "
            "String-dominant blocks filtered; tests/examples/docs downgraded; "
            "clusters of >5 copies collapse to one info.",
        "risk.error-masking":
            "except body is only pass/…, split by broadness: "
            "bare `except:` or `except Exception:` → warn; "
            "`except SpecificError:` → info.",
        "except.reraise-vs-raise":
            "`raise <alias>` in `except X as <alias>:` truncates traceback. "
            "Bare `raise` preserves it.",
        "arg.mutable-default":
            "Default is evaluated once at def-time. `def f(x=[]):` shares "
            "one list across every call — classic hidden state.",
        "test.assertion-free":
            "test_* function with no assert*, pytest.raises, or unittest self.assert*. "
            "Runs, passes, checks nothing.",
        "test.always-true-assertion":
            "assert on a truthy literal (True, non-empty container, non-zero number). "
            "Always passes regardless of code.",
        "test.no-test-for-public-symbol":
            "Public top-level symbol has no test_<name> anywhere in the parallel "
            "tests/ tree.",
        "test.time.sleep":
            "`time.sleep(...)` inside a test_* function. Waiting on wall time in "
            "tests is a flakiness antipattern; use event-driven waits.",
    },
    "ko": {
        "dup.block":
            "함수 본문 안에서 5행 이상 중복되는 코드 블록. "
            "문자열 위주 블록은 걸러내고, tests/examples/docs는 등급 강등, "
            "5개 초과 클러스터는 info 하나로 축약.",
        "risk.error-masking":
            "except 본문이 pass/… 뿐인 경우. 예외 광범위성으로 분류: "
            "bare `except:` 또는 `except Exception:` → warn, "
            "`except 특정예외:` → info.",
        "except.reraise-vs-raise":
            "`except X as e:` 다음 `raise e`는 원래 traceback을 잘라냄. "
            "그냥 `raise`만 쓰면 traceback이 보존됨.",
        "arg.mutable-default":
            "기본값은 def 선언 시점에 1회 평가됨. `def f(x=[]):`는 "
            "모든 호출이 하나의 리스트를 공유 — 대표적인 숨은 상태 버그.",
        "test.assertion-free":
            "test_* 함수인데 assert*, pytest.raises, self.assert* 어느 것도 없음. "
            "실행되고 통과하지만 아무것도 검증 안 함.",
        "test.always-true-assertion":
            "항상 참인 리터럴에 대한 assert (True, 비어있지 않은 컨테이너, 0이 아닌 숫자). "
            "코드와 무관하게 항상 통과함.",
        "test.no-test-for-public-symbol":
            "public 최상위 심볼이지만 tests/ 트리에 대응하는 test_<name>이 없음.",
        "test.time.sleep":
            "test_* 함수 안의 `time.sleep(...)`. 테스트에서 실시간 대기는 "
            "flaky 신호 — 이벤트 기반 대기(async, fixture)로 바꿔야 함.",
    },
}


# UI strings for the dashboard. Any key missing in "ko" falls back to "en".
_STRINGS = {
    "en": {
        "connecting": "connecting…",
        "live": "live", "scanning": "scanning…", "disconnected": "disconnected",
        "block": "block", "warn": "warn", "info": "info",
        "files": "files",
        "mode_new": "new only", "mode_all": "all", "mode_baselined": "baselined",
        "mode_new_title": "hide baselined findings (press N)",
        "mode_all_title": "show every finding",
        "mode_baselined_title": "show only baselined findings",
        "search": "filter by file, analyzer, symbol…  /",
        "help_btn": "show keyboard shortcuts",
        "of": "of",
        "risk_title": "Risk", "risk_hint": "findings · j / k to navigate",
        "evidence_title": "Evidence",
        "evidence_empty_html":
            "Select a finding — press <kbd>j</kbd> or click a row.",
        "delta_title": "Delta · analyzer counts",
        "delta_hint": "& recent scans",
        "no_findings_match": "No findings match the current filters.",
        "no_findings": "no findings",
        "waiting": "waiting…",
        "how_detected": "How this was detected",
        "snippet": "Snippet",
        "matches": "Matches",
        "raw_evidence": "Raw evidence",
        "baseline_tag": "baseline",
        "help_h": "keyboard",
        "help_jk": "next / previous finding",
        "help_enter": "expand selected finding",
        "help_123": "toggle block / warn / info",
        "help_n": "cycle: new only → all → baselined",
        "help_slash": "focus search",
        "help_esc": "blur search / close this",
        "help_q": "toggle this overlay",
        "activity_findings": "findings",
        "activity_files": "files",
        "system_title": "System · pipeline",
        "system_hint": "threads · analyzer timings · state machine",
        "phase_starting": "starting", "phase_idle": "idle",
        "phase_detecting": "detecting", "phase_debouncing": "debouncing",
        "phase_scanning": "scanning", "phase_emitting": "emitting",
        "phase_stuck_suffix": " · stuck",
        "in_state": "in state",
        "recent_events": "Recent transitions",
        "sys_stage": "Stage timings",
        "sys_no_scan": "No scan yet",
        "sys_threads": "Threads",
        "sys_uptime": "Uptime",
        "sys_waiters": "Long-poll clients",
        "sys_version": "State version",
        "sys_idx_err": "Indexer errors",
        "sys_ana_err": "Analyzer errors",
        "sys_version_short": "v",
        "sys_uptime_short": "up",
        "sys_waiters_short": "waiters",
        "sys_threads_short": "threads",
        "sys_timing_total": "total",
        "sys_timing_index": "index",
        "sys_timing_changeset": "parse",
        "sys_waiting": "waiting for first scan…",
        "tracing": "tracing",
        "trace_clear": "clear",
        "trace_kind_analyzer": "analyzer",
        "trace_kind_file": "file",
        "trace_hits": "matches",
        "trace_hint": "click a location or analyzer id to trace across panels",
    },
    "ko": {
        "connecting": "연결 중…",
        "live": "실시간", "scanning": "스캔 중…", "disconnected": "연결 끊김",
        "block": "block", "warn": "warn", "info": "info",
        "files": "파일",
        "mode_new": "신규만", "mode_all": "전체", "mode_baselined": "baseline",
        "mode_new_title": "baseline에 있는 것 숨김 (N 키)",
        "mode_all_title": "모든 finding 표시",
        "mode_baselined_title": "baseline에 있는 것만 표시",
        "search": "파일 / analyzer / symbol 검색…  /",
        "help_btn": "키보드 단축키",
        "of": "/",
        "risk_title": "위험도", "risk_hint": "findings · j / k 로 이동",
        "evidence_title": "근거",
        "evidence_empty_html":
            "finding을 선택하세요 — <kbd>j</kbd> 키 또는 행 클릭.",
        "delta_title": "델타 · analyzer 별 개수",
        "delta_hint": "· 최근 스캔",
        "no_findings_match": "현재 필터에 해당하는 finding이 없습니다.",
        "no_findings": "finding 없음",
        "waiting": "대기 중…",
        "how_detected": "탐지 근거",
        "snippet": "코드",
        "matches": "매치",
        "raw_evidence": "원본 evidence",
        "baseline_tag": "baseline",
        "help_h": "키보드",
        "help_jk": "다음 / 이전 finding",
        "help_enter": "선택된 finding 펼치기",
        "help_123": "block / warn / info 토글",
        "help_n": "사이클: 신규만 → 전체 → baseline",
        "help_slash": "검색 포커스",
        "help_esc": "검색 blur / 닫기",
        "help_q": "이 오버레이 토글",
        "activity_findings": "findings",
        "activity_files": "파일",
        "system_title": "시스템 · 파이프라인",
        "system_hint": "스레드 · analyzer 타이밍 · 상태 머신",
        "phase_starting": "시작 중", "phase_idle": "대기",
        "phase_detecting": "감지 중", "phase_debouncing": "디바운스",
        "phase_scanning": "스캔 중", "phase_emitting": "전송",
        "phase_stuck_suffix": " · 정체",
        "in_state": "이 상태",
        "recent_events": "최근 상태 전환",
        "sys_stage": "단계별 소요",
        "sys_no_scan": "스캔 대기 중",
        "sys_threads": "스레드",
        "sys_uptime": "가동",
        "sys_waiters": "long-poll 클라이언트",
        "sys_version": "상태 버전",
        "sys_idx_err": "인덱서 오류",
        "sys_ana_err": "analyzer 오류",
        "sys_version_short": "v",
        "sys_uptime_short": "가동",
        "sys_waiters_short": "대기 클라",
        "sys_threads_short": "스레드",
        "sys_timing_total": "합계",
        "sys_timing_index": "인덱스",
        "sys_timing_changeset": "파싱",
        "sys_waiting": "첫 스캔 대기 중…",
        "tracing": "추적",
        "trace_clear": "해제",
        "trace_kind_analyzer": "analyzer",
        "trace_kind_file": "파일",
        "trace_hits": "매칭",
        "trace_hint": "위치나 analyzer id를 클릭하면 여러 패널에 걸쳐 추적됨",
    },
}


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.version = 0
        self.envelope: dict | None = None
        self.scanning = False
        self.activity: collections.deque = collections.deque(maxlen=ACTIVITY_LEN)
        self.prev_ids: set[str] = set()
        # Pipeline state machine + system telemetry surfaced to the UI.
        self.phase = "starting"     # idle | detecting | debouncing | scanning | emitting
        self.phase_at = time.monotonic()
        self.waiters = 0            # long-poll clients currently blocked in wait_after
        self.events: collections.deque = collections.deque(maxlen=30)
        self.started_at = time.time()

    def set_phase(self, phase: str, detail: str = "") -> None:
        with self.cond:
            now = time.monotonic()
            elapsed = now - self.phase_at
            self.events.appendleft({
                "at": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "phase": phase,
                "detail": detail,
                "prev_ms": round(elapsed * 1000),
            })
            self.phase = phase
            self.phase_at = now
            self.cond.notify_all()

    def set(self, envelope: dict) -> None:
        """Publish a new envelope. INVARIANT: once handed to set(),
        the envelope dict is treated as read-only for the rest of its
        life — HTTP handlers may serialize it concurrently. Callers
        must build the envelope fully before this call. `_scan` +
        `to_json` produce a fresh dict per call (dataclasses.asdict
        recurses), so today's callers already satisfy this."""
        with self.cond:
            self.version += 1
            cur_ids = {f["id"] for f in envelope["findings"]}
            delta_new = len(cur_ids - self.prev_ids)
            delta_gone = len(self.prev_ids - cur_ids)
            self.prev_ids = cur_ids
            self.activity.appendleft({
                "at": datetime.datetime.now().strftime("%H:%M:%S"),
                "files": envelope["summary"]["files_scanned"],
                "total": len(cur_ids),
                "new": delta_new,
                "gone": delta_gone,
            })
            envelope["activity"] = list(self.activity)
            envelope["analyzer_counts"] = _counts_by_analyzer(envelope["findings"])
            self.envelope = envelope
            self.cond.notify_all()

    def wait_after(self, since: int, timeout: float) -> tuple[int, dict | None, bool]:
        with self.cond:
            if self.version > since:
                return self.version, self.envelope, self.scanning
            self.waiters += 1
            self.cond.notify_all()   # let system.json see the new waiter count
            try:
                self.cond.wait(timeout=timeout)
            finally:
                self.waiters -= 1
            return self.version, self.envelope, self.scanning

    def set_scanning(self, on: bool) -> None:
        with self.cond:
            self.scanning = on
            self.cond.notify_all()

    def snapshot_system(self) -> dict:
        """Runtime telemetry — safe to read without touching the envelope."""
        with self.cond:
            return {
                "phase": self.phase,
                "phase_elapsed_ms": round((time.monotonic() - self.phase_at) * 1000),
                "waiters": self.waiters,
                "version": self.version,
                "uptime_s": round(time.time() - self.started_at, 1),
                "threads": [
                    {"name": t.name, "daemon": t.daemon, "alive": t.is_alive()}
                    for t in threading.enumerate()
                ],
                "events": list(self.events),
            }


_state = _State()


def _counts_by_analyzer(findings: list[dict]) -> list[dict]:
    """Sorted analyzer counts split by severity, for the bar chart."""
    by = {}
    for f in findings:
        by.setdefault(f["analyzer_id"], {"block": 0, "warn": 0, "info": 0})
        by[f["analyzer_id"]][f["severity"]] += 1
    out = [{"id": k, **v, "total": v["block"] + v["warn"] + v["info"]}
           for k, v in by.items()]
    out.sort(key=lambda x: (-x["total"], x["id"]))
    return out


_scanner = IncrementalScanner()


def _scan(repo: Path, force_full: bool = False) -> dict:
    """Wrap incremental scan with baseline + rationale annotations."""
    env = _scanner.scan(repo, force_full=force_full, set_phase=_state.set_phase)
    # Best-effort persistence: dump the caches so the next process start
    # skips the cold scan. Silent on failure — never blocks the watch loop.
    _scanner.save(repo)

    baselined = bl.load(repo)
    env["has_baseline"] = baselined is not None
    baselined = baselined or set()
    for f in env["findings"]:
        f["baselined"] = f["id"] in baselined
        aid = f["analyzer_id"]
        f["rationale"] = _RATIONALES["en"].get(aid, "")
        f["rationale_ko"] = _RATIONALES["ko"].get(aid, "")
    env["summary"]["baselined"] = sum(1 for f in env["findings"] if f["baselined"])
    env["summary"]["new"] = len(env["findings"]) - env["summary"]["baselined"]
    return env


def _watch_loop(repo: Path) -> None:
    """Watch the repo forever. Any exception inside a scan is logged and
    the loop continues — a crashed scan must never wedge the UI into
    perpetual "scanning…" (previous versions did exactly that)."""
    def _safe_scan(force_full: bool = False) -> None:
        _state.set_scanning(True)
        try:
            _state.set(_scan(repo, force_full=force_full))
        except Exception:
            print("cockpit serve: scan failed:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        finally:
            _state.set_scanning(False)
            _state.set_phase("idle")

    # Warm-start from `.cockpit/state/` if it survived a previous run.
    # load() is silent on miss/corrupt so it never blocks cold scan.
    warm = _scanner.load(repo)
    _state.set_phase("scanning", "warm resume" if warm else "cold start")
    _safe_scan(force_full=not warm)

    prev = _snapshot(repo)
    last_change_at: float | None = None
    while True:
        try:
            time.sleep(POLL_INTERVAL)
            cur = _snapshot(repo)
            if cur != prev:
                changed = _changed_paths(prev, cur)
                _state.set_phase("debouncing",
                                 f"{len(changed)} files (waiting {DEBOUNCE:.1f}s quiet)")
                last_change_at = time.monotonic()
                prev = cur
            elif last_change_at is not None and \
                    time.monotonic() - last_change_at >= DEBOUNCE:
                _safe_scan()
                last_change_at = None
        except Exception:
            print("cockpit serve: watch loop error:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            time.sleep(POLL_INTERVAL)   # backoff before retrying


def _changed_paths(prev: dict[str, float], cur: dict[str, float]) -> list[str]:
    added = cur.keys() - prev.keys()
    removed = prev.keys() - cur.keys()
    modified = {k for k in cur.keys() & prev.keys() if cur[k] != prev[k]}
    return sorted(added | removed | modified)[:20]


MAX_WAITERS = 64           # long-poll fairness cap; past this we 503
_ALLOWED_HOSTS: set[str] = set()   # populated by cmd_serve


class _Handler(BaseHTTPRequestHandler):
    # Kill slowloris — a client that opens a socket and never sends bytes
    # will otherwise hold a thread until TCP FIN.
    timeout = 15

    # Drop the "Server: BaseHTTP/0.6 Python/3.11.x" fingerprint.
    def version_string(self) -> str:
        return "cockpit"

    def log_message(self, format: str, *args) -> None:
        pass  # ponytail: silence per-request access log

    def _host_ok(self) -> bool:
        """Reject requests with a Host header outside the allowlist.
        DNS-rebinding defense: an external site can otherwise coerce
        the browser into fetching http://127.0.0.1:port under its own
        origin and reading source snippets."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not _ALLOWED_HOSTS:
            return True   # allowlist not configured — off by default
        return host in _ALLOWED_HOSTS

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send(400, "text/plain", b"host header rejected")
            return
        try:
            url = urlparse(self.path)
        except ValueError:
            self._send(400, "text/plain", b"bad url")
            return
        if url.path == "/":
            strings_json = json.dumps(_STRINGS, ensure_ascii=False)
            # Belt-and-suspenders against payload closing the injecting script tag.
            strings_json = strings_json.replace("</", "<\\/")
            page = _PAGE.replace("__STRINGS_JSON__", strings_json)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif url.path == "/state.json":
            try:
                since = int((parse_qs(url.query).get("since") or ["-1"])[0])
            except (ValueError, TypeError):
                self._send(400, "application/json",
                           b'{"error":"bad since"}')
                return
            if _state.waiters >= MAX_WAITERS:
                self._send(503, "application/json",
                           b'{"error":"too many waiters"}')
                return
            version, envelope, scanning = _state.wait_after(since, WAIT_TIMEOUT)
            body = json.dumps({
                "version": version,
                "envelope": envelope,
                "scanning": scanning,
                "system": _state.snapshot_system(),
            }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body)
        elif url.path == "/system.json":
            body = json.dumps(_state.snapshot_system(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body)
        else:
            self._send(404, "text/plain", b"not found")

    def do_HEAD(self) -> None:  # trivially supportable; some health checks use it
        self.do_GET()

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # Defence-in-depth against injection into the HTML page:
            # no framing, no MIME sniffing, no cross-origin embedding.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; "
                    "script-src 'unsafe-inline'; "  # inline JS is core to _PAGE
                    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
                    "font-src https://fonts.gstatic.com; "
                    "connect-src 'self'; "
                    "img-src 'self' data:; "
                    "frame-ancestors 'none'",
                )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Client disconnected mid-response. Fine — nothing to log.
            pass


def cmd_serve(repo: Path, port: int = 8765, host: str = "127.0.0.1") -> int:
    t = threading.Thread(target=_watch_loop, args=(repo,), daemon=True)
    t.start()

    # Populate Host-header allowlist for DNS-rebinding defense.
    _ALLOWED_HOSTS.clear()
    _ALLOWED_HOSTS.update({
        f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}",
        f"127.0.0.1", "localhost", "[::1]",
    })
    if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::"):
        _ALLOWED_HOSTS.update({f"{host}:{port}", host})

    httpd = ThreadingHTTPServer((host, port), _Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}"
    print(f"cockpit serve · {url}  (Ctrl-C to stop)")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  ⚠  listening on {host}:{port} — reachable from other hosts on this network.",
              file=sys.stderr)
        print(f"     Findings, source snippets, and errors are served without auth.",
              file=sys.stderr)
        print(f"     Restrict to a Tailscale/VPN IP, or use --host 127.0.0.1.",
              file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
        httpd.shutdown()
        return 0


_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cockpit — live</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #fdfdfd; --panel: #ffffff; --fg: #1a1a1a; --muted: #666;
  --border: #ddd; --stripe: #f6f6f6; --code-bg: #f0f0f0;
  --block: #c62828; --warn: #d97706; --info: #0369a1;
  --live: #16a34a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141414; --panel: #1c1c1c; --fg: #eee; --muted: #999;
    --border: #333; --stripe: #242424; --code-bg: #262626;
    --block: #ef5350; --warn: #fbbf24; --info: #38bdf8;
    --live: #4ade80;
  }
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; padding: 0.75rem 1rem;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--fg);
  display: grid; grid-template-rows: auto auto 1fr; gap: 0.5rem; }
header { display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
h1 { font-size: 1.1rem; margin: 0; font-weight: 600; }
.repo { color: var(--muted); font-family: ui-monospace, monospace; font-size: 0.85rem; }
.summary { display: flex; gap: 0.5rem; }
.summary span { padding: 0.15rem 0.5rem; border-radius: 3px; font-weight: 600; font-size: 0.85rem; }
.summary .n-block { background: var(--block); color: #fff; }
.summary .n-warn { background: var(--warn); color: #fff; }
.summary .n-info { background: var(--info); color: #fff; }
.summary .n-zero { background: transparent; color: var(--muted); font-weight: 400; }
.live { display: inline-flex; align-items: center; gap: 0.35rem; color: var(--live); font-size: 0.85rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--live);
  box-shadow: 0 0 0 0 currentColor; animation: pulse 1.6s ease-out infinite; }
.dot.scanning { animation: pulse 0.6s ease-out infinite; }
.dot.stale { background: var(--muted); animation: none; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
  70% { box-shadow: 0 0 0 8px transparent; opacity: 0.9; }
  100% { box-shadow: 0 0 0 0 transparent; opacity: 1; }
}
.filters { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
.filters label { display: flex; gap: 0.25rem; align-items: center; user-select: none; cursor: pointer; }
.filters input[type=text] { padding: 0.25rem 0.5rem; border: 1px solid var(--border);
  background: var(--bg); color: var(--fg); border-radius: 3px; min-width: 20ch; }
.count { color: var(--muted); font-size: 0.85rem; margin-left: auto; }

/* Trace bar — appears when the user starts a route trace. */
.trace-bar { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0.75rem;
  background: color-mix(in srgb, var(--live) 8%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--live) 35%, var(--border));
  border-radius: 4px; font-size: 0.82rem; font-family: ui-monospace, monospace;
  animation: traceBarIn 220ms ease-out; }
.trace-bar[hidden] { display: none; }
.trace-bar .k { color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em;
  font-size: 0.68rem; font-family: system-ui, -apple-system, sans-serif; }
.trace-bar code { background: transparent; color: var(--fg); font-weight: 600; }
.trace-bar .hits { color: var(--muted); }
.trace-bar .close { margin-left: auto; border: 1px solid var(--border); background: var(--bg);
  color: var(--fg); cursor: pointer; padding: 0.15rem 0.55rem; border-radius: 3px;
  font: inherit; font-size: 0.72rem; }
.trace-bar .close:hover { background: var(--stripe); }
@keyframes traceBarIn { from { opacity: 0; transform: translateY(-2px); } to { opacity: 1; transform: none; } }

/* Trace-src elements — inline click targets. */
.trace-src { cursor: pointer; border-bottom: 1px dotted transparent; transition: border-color 120ms, color 120ms; }
.trace-src:hover { border-bottom-color: var(--live); color: var(--fg); }

/* Trace-active states. Dim non-matches, keep matches vivid. */
tr.finding.dim { opacity: 0.22; }
tr.finding.trace-hit { background: color-mix(in srgb, var(--live) 6%, transparent); }
tr.finding.trace-hit td.loc { box-shadow: inset 3px 0 0 var(--live); }
.chart-row.dim { opacity: 0.22; }
.chart-row.trace-hit .bar { outline: 2px solid color-mix(in srgb, var(--live) 55%, transparent); outline-offset: 1px; }
.chart-row .name { cursor: pointer; }
.chart-row .name:hover { color: var(--fg); }
#sys-svg .tim-seg { cursor: pointer; }
#sys-svg .tim-seg.dim { opacity: 0.25; }
#sys-svg .tim-seg.trace-hit { filter: drop-shadow(0 0 4px var(--live)); }
#sys-svg .pip { cursor: pointer; }
#sys-svg .pip.dim { opacity: 0.15; }

main { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  grid-template-rows: minmax(0, 1fr) 170px 210px; gap: 0.5rem; min-height: 0; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 4px;
  display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.panel > h2 { margin: 0; padding: 0.4rem 0.75rem;
  font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border); display: flex; gap: 0.5rem; align-items: center; }
.panel > h2 .killer { color: var(--warn); }
.panel-body { flex: 1; overflow: auto; min-height: 0; }

.risk { grid-column: 1; grid-row: 1; }
.evidence { grid-column: 2; grid-row: 1 / span 2; }
.delta { grid-column: 1; grid-row: 2; }
.system { grid-column: 1 / span 2; grid-row: 3; }
.system .panel-body { display: grid; grid-template-rows: 26px 1fr; padding: 0; min-height: 0; }
.sys-stats { display: flex; gap: 1rem; align-items: center; padding: 0 0.9rem;
  font-family: ui-monospace, monospace; font-size: 0.72rem; color: var(--muted);
  border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.sys-stats .k { opacity: 0.65; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.65rem; margin-right: 0.25rem; }
.sys-stats .v { color: var(--fg); }
.sys-stats .v.warn { color: var(--warn); font-weight: 600; }
.sys-stats .thread-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  vertical-align: middle; margin-right: 0.3rem; background: var(--live); }
.sys-stats .thread-dot.amber { background: var(--warn); }
.sys-stats .thread-dot.red { background: var(--block); }
.sys-stats .spacer { flex: 1; }
#sys-svg { width: 100%; height: 100%; display: block; overflow: visible; }
#sys-svg .label { font: 500 11px system-ui, -apple-system, sans-serif; fill: var(--muted); text-anchor: middle; }
#sys-svg .label.current { fill: var(--fg); }
#sys-svg .elapsed { font: 500 11px ui-monospace, monospace; fill: var(--fg); text-anchor: middle; font-variant-numeric: tabular-nums; }
#sys-svg .node { fill: none; stroke: var(--muted); stroke-width: 2; transition: stroke 200ms, fill 200ms; }
#sys-svg .node.done { fill: color-mix(in srgb, var(--info) 40%, transparent); stroke: var(--info); }
#sys-svg .node.current { fill: var(--live); stroke: var(--live); }
#sys-svg .node.current.stuck { fill: var(--warn); stroke: var(--warn); }
#sys-svg .node.current.err { stroke: var(--block); stroke-width: 2.5; }
#sys-svg .connector { stroke: var(--muted); stroke-width: 2; transition: stroke 240ms; }
#sys-svg .connector.done { stroke: var(--info); }
#sys-svg .ring { fill: none; stroke: var(--live); stroke-width: 2; transform-origin: center; transform: rotate(-90deg); transition: stroke-dashoffset 500ms linear; }
#sys-svg .pulse { fill: var(--live); opacity: 0.35; animation: sysPulse 1600ms ease-out infinite; }
#sys-svg .pulse.stuck { fill: var(--warn); animation-duration: 2600ms; }
@keyframes sysPulse {
  0%   { r: 22; opacity: 0.5; }
  100% { r: 34; opacity: 0; }
}
#sys-svg .pip { fill: color-mix(in srgb, var(--muted) 40%, transparent); transition: fill 180ms, r 180ms; }
#sys-svg .pip.done { fill: var(--info); }
#sys-svg .pip.active { fill: var(--live); r: 4.5; }
#sys-svg .tim-seg { transition: opacity 220ms; }
#sys-svg .tim-seg.err { stroke: var(--block); stroke-width: 2; }
#sys-svg .tim-hdr { font: 500 10px ui-monospace, monospace; fill: var(--muted); font-variant-numeric: tabular-nums; }
#sys-svg .tim-label { font: 500 9px ui-monospace, monospace; fill: var(--muted); text-anchor: middle; }
#sys-svg .tim-empty { font: 500 11px system-ui, -apple-system, sans-serif; font-style: italic; fill: var(--muted); text-anchor: middle; }
#sys-svg .strip-in { animation: stripIn 280ms ease-out; }
@keyframes stripIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@keyframes errorFlash {
  0%, 100% { stroke: var(--block); } 50% { stroke: transparent; }
}
#sys-svg .flash { animation: errorFlash 600ms ease-in-out 2; }
@media (prefers-reduced-motion: reduce) {
  #sys-svg .pulse, #sys-svg .strip-in, #sys-svg .flash { animation: none; }
  #sys-svg .ring { transition: none; }
}
.evidence-empty { padding: 1.5rem; color: var(--muted); font-size: 0.85rem; text-align: center; }

table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
thead th { position: sticky; top: 0; background: var(--panel); z-index: 1; font-size: 0.75rem; color: var(--muted); }
tr:nth-child(even) { background: var(--stripe); }
tr.finding.fresh { animation: flash 1.2s ease-out; }
tr.finding.selected { outline: 2px solid var(--live); outline-offset: -2px; background: color-mix(in srgb, var(--live) 8%, transparent); }
tr.finding.baselined { opacity: 0.55; }
tr.finding.baselined td.loc::after { content: " · baseline"; color: var(--muted); font-size: 0.75rem; }
@keyframes flash {
  0% { background: color-mix(in srgb, var(--live) 30%, var(--bg)); }
  100% { background: transparent; }
}
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
.seg button { border: 0; background: var(--bg); color: var(--fg); padding: 0.2rem 0.6rem;
  font: inherit; font-size: 0.85rem; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button.active { background: var(--live); color: #fff; }
kbd { font-family: ui-monospace, monospace; font-size: 0.75rem; padding: 0.05rem 0.35rem;
  border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 3px;
  background: var(--stripe); color: var(--fg); }
.help-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex;
  align-items: center; justify-content: center; z-index: 10; }
.help-overlay[hidden] { display: none; }
.help-card { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 1.25rem 1.5rem; min-width: 320px; max-width: 480px; }
.help-card h2 { margin: 0 0 0.75rem; font-size: 1rem; }
.help-card table { border: 0; }
.help-card td { border: 0; padding: 0.2rem 0.5rem 0.2rem 0; }
.help-card td:first-child { text-align: right; width: 8em; }
.sev { display: inline-block; width: 3.3em; padding: 0.05rem 0.35rem; border-radius: 3px;
  font-size: 0.75rem; font-weight: 700; color: #fff; text-align: center; text-transform: uppercase; }
.sev.block { background: var(--block); }
.sev.warn { background: var(--warn); }
.sev.info { background: var(--info); }
.loc { font-family: ui-monospace, monospace; font-size: 0.85rem; color: var(--muted); white-space: nowrap; }
.ana { font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--muted); }
tr.hidden { display: none; }
tr.finding.expanded + tr.evidence { display: table-row; }
tr.evidence { display: none; }
tr.evidence td { background: var(--code-bg); padding: 0.5rem 0.75rem; border-top: none; }
tr.evidence pre { margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--fg); }
tr.finding { cursor: pointer; }
tr.finding:hover { background: var(--stripe); }
.empty { padding: 2rem; text-align: center; color: var(--muted); }

/* EVIDENCE panel */
.ev { padding: 0.75rem 1rem; }
.ev .loc { font-family: ui-monospace, monospace; font-size: 0.9rem; margin-bottom: 0.5rem; color: var(--fg); }
.ev .rule { color: var(--muted); font-size: 0.8rem; margin-bottom: 0.5rem; }
.ev .msg { font-size: 0.95rem; margin-bottom: 0.75rem; }
.ev section { margin-top: 0.75rem; }
.ev section > h3 { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin: 0 0 0.35rem; }
.ev pre { background: var(--code-bg); padding: 0.6rem 0.75rem; border-radius: 3px;
  font-family: ui-monospace, monospace; font-size: 0.78rem; overflow: auto;
  white-space: pre-wrap; word-break: break-word; margin: 0; }
.ev .matches { display: flex; flex-direction: column; gap: 0.25rem; font-family: ui-monospace, monospace; font-size: 0.8rem; }
.ev .matches a { color: var(--fg); text-decoration: none; padding: 0.15rem 0.35rem; border-radius: 2px; }
.ev .matches a:hover { background: var(--stripe); }

/* DELTA (analyzer bar chart) */
.chart-row { display: grid; grid-template-columns: 12em 1fr 3em; gap: 0.5rem;
  align-items: center; padding: 0.15rem 0.75rem; font-size: 0.8rem; }
.chart-row .name { font-family: ui-monospace, monospace; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chart-row .bar { height: 0.55rem; background: var(--stripe); border-radius: 2px; overflow: hidden;
  display: flex; }
.chart-row .bar span { display: block; height: 100%; }
.chart-row .bar .block { background: var(--block); }
.chart-row .bar .warn { background: var(--warn); }
.chart-row .bar .info { background: var(--info); }
.chart-row .n { font-family: ui-monospace, monospace; text-align: right; color: var(--muted); }
.chart-empty { padding: 1rem; color: var(--muted); font-size: 0.85rem; text-align: center; }

/* NOW activity log (embedded in DELTA panel footer strip) */
.activity { display: flex; flex-direction: column; gap: 0.1rem; padding: 0.35rem 0.75rem; font-family: ui-monospace, monospace; font-size: 0.78rem; }
.activity .row { display: grid; grid-template-columns: 4.5em 1fr auto; gap: 0.5rem; color: var(--muted); }
.activity .row .delta.pos { color: var(--warn); }
.activity .row .delta.neg { color: var(--live); }
</style>

<header>
  <h1>cockpit</h1>
  <span class="repo" id="repo" data-t="connecting">connecting…</span>
  <div class="summary" id="summary"></div>
  <span class="live"><span class="dot" id="dot"></span><span id="livetext" data-t="live">live</span></span>
  <span class="seg" id="lang-mode" role="group" aria-label="language" style="margin-left:auto;">
    <button data-lang="en">EN</button>
    <button data-lang="ko">KO</button>
  </span>
</header>

<div class="trace-bar" id="trace-bar" hidden>
  <span class="k" data-t="tracing">tracing</span>
  <span id="trace-desc"></span>
  <button class="close" id="trace-close" data-t="trace_clear" title="Esc">clear</button>
</div>

<div class="filters">
  <label><input type="checkbox" id="f-block" checked> <span data-t="block">block</span> <kbd>1</kbd></label>
  <label><input type="checkbox" id="f-warn" checked> <span data-t="warn">warn</span> <kbd>2</kbd></label>
  <label><input type="checkbox" id="f-info"> <span data-t="info">info</span> <kbd>3</kbd></label>
  <span class="seg" id="baseline-mode" role="group" aria-label="baseline filter">
    <button data-mode="new" class="active" data-t="mode_new" data-t-title="mode_new_title">new only</button>
    <button data-mode="all" data-t="mode_all" data-t-title="mode_all_title">all</button>
    <button data-mode="baselined" data-t="mode_baselined" data-t-title="mode_baselined_title">baselined</button>
  </span>
  <input type="text" id="q" data-t-placeholder="search" placeholder="filter by file, analyzer, symbol…  /">
  <span class="count" id="count"></span>
  <button id="help-btn" data-t-title="help_btn" style="border:1px solid var(--border);background:var(--bg);color:var(--muted);border-radius:3px;padding:0.15rem 0.5rem;cursor:pointer;font:inherit;font-size:0.85rem;">?</button>
</div>

<div class="help-overlay" id="help" hidden>
  <div class="help-card">
    <h2 data-t="help_h">keyboard</h2>
    <table>
      <tr><td><kbd>j</kbd> / <kbd>k</kbd></td><td data-t="help_jk">next / previous finding</td></tr>
      <tr><td><kbd>Enter</kbd></td><td data-t="help_enter">expand selected finding</td></tr>
      <tr><td><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></td><td data-t="help_123">toggle block / warn / info</td></tr>
      <tr><td><kbd>n</kbd></td><td data-t="help_n">cycle: new only → all → baselined</td></tr>
      <tr><td><kbd>/</kbd></td><td data-t="help_slash">focus search</td></tr>
      <tr><td><kbd>Esc</kbd></td><td data-t="help_esc">blur search / close this</td></tr>
      <tr><td><kbd>?</kbd></td><td data-t="help_q">toggle this overlay</td></tr>
    </table>
  </div>
</div>

<main>
  <section class="panel risk">
    <h2><span data-t="risk_title">Risk</span> <span class="killer">★</span> <span data-t="risk_hint" style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;">findings · j / k to navigate</span></h2>
    <div class="panel-body">
      <table>
        <thead>
          <tr>
            <th style="width:5em">sev</th>
            <th>file:line</th>
            <th style="width:11em">analyzer</th>
            <th>message</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div id="empty" class="empty" hidden data-t="no_findings_match">No findings match the current filters.</div>
    </div>
  </section>

  <section class="panel evidence">
    <h2 data-t="evidence_title">Evidence</h2>
    <div class="panel-body" id="evidence-body"></div>
  </section>

  <section class="panel delta">
    <h2><span data-t="delta_title">Delta · analyzer counts</span> <span data-t="delta_hint" style="margin-left:auto;color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;">& recent scans</span></h2>
    <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:0;">
      <div id="chart" style="border-right:1px solid var(--border);overflow:auto;"></div>
      <div id="activity" class="activity"></div>
    </div>
  </section>

  <section class="panel system">
    <h2><span data-t="system_title">System · pipeline</span>
      <span data-t="system_hint" style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;">state machine · analyzer timings</span></h2>
    <div class="panel-body">
      <div class="sys-stats" id="sys-stats"></div>
      <svg id="sys-svg" viewBox="0 0 1600 156" preserveAspectRatio="xMidYMid meet" aria-label="pipeline visualization"></svg>
    </div>
  </section>
</main>

<script>
const SEV_ORDER = { block: 0, warn: 1, info: 2 };
const BASELINE_MODES = ["new", "all", "baselined"];
const STRINGS = __STRINGS_JSON__;
let version = -1;
let findings = [];
let prevIds = new Set();
let baselineMode = "new";
let selectedIdx = -1;
let modeAutoPicked = false;  // first envelope sets initial mode based on has_baseline
let lang = "en";
let trace = null;   // {kind: "analyzer"|"file", value: "..."} — inspired by Archify

function matchesTrace(kind, value) {
  if (!trace) return true;
  if (trace.kind === "analyzer" && kind === "analyzer") return value === trace.value;
  if (trace.kind === "file" && kind === "file") return value === trace.value;
  return false;
}
function findingMatchesTrace(f) {
  if (!trace) return true;
  if (trace.kind === "analyzer") return f.analyzer_id === trace.value;
  if (trace.kind === "file") return f.file === trace.value;
  return false;
}
function setTrace(kind, value) {
  if (!kind || !value) return;
  if (trace && trace.kind === kind && trace.value === value) { clearTrace(); return; }
  trace = { kind, value };
  applyFilter();
  renderTraceBar();
  // Re-render chart + system so dim states appear.
  const env = window.__lastEnvelope;
  if (env) renderChart(env.analyzer_counts || []);
  if (env && window.__lastSys) renderSystem(window.__lastSys, env.timings, env.errors);
}
function clearTrace() {
  if (!trace) return;
  trace = null;
  applyFilter();
  renderTraceBar();
  const env = window.__lastEnvelope;
  if (env) renderChart(env.analyzer_counts || []);
  if (env && window.__lastSys) renderSystem(window.__lastSys, env.timings, env.errors);
}
function renderTraceBar() {
  const bar = document.getElementById("trace-bar");
  if (!trace) { bar.hidden = true; return; }
  bar.hidden = false;
  const hits = findings.filter(findingMatchesTrace).length;
  const kindLabel = t("trace_kind_" + trace.kind);
  document.getElementById("trace-desc").innerHTML =
    `${esc(kindLabel)} = <code>${esc(trace.value)}</code> <span class="hits">· ${hits} ${t("trace_hits")}</span>`;
}
// Delegated trace clicks — any element with data-trace-kind + data-trace-value.
document.addEventListener("click", (e) => {
  const src = e.target.closest("[data-trace-kind]");
  if (!src) return;
  const kind = src.dataset.traceKind;
  const value = src.dataset.traceValue;
  if (!kind || value === undefined) return;
  e.stopPropagation();
  setTrace(kind, value);
});
document.getElementById("trace-close").addEventListener("click", clearTrace);

function t(key) {
  return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
}

function applyLang(next) {
  lang = STRINGS[next] ? next : "en";
  try { localStorage.setItem("cockpit.lang", lang); } catch {}
  document.documentElement.lang = lang;
  document.querySelectorAll("#lang-mode button").forEach(b =>
    b.classList.toggle("active", b.dataset.lang === lang));
  for (const el of document.querySelectorAll("[data-t]")) {
    const v = t(el.dataset.t);
    if (el.dataset.t.endsWith("_html")) el.innerHTML = v;
    else el.textContent = v;
  }
  for (const el of document.querySelectorAll("[data-t-title]"))
    el.title = t(el.dataset.tTitle);
  for (const el of document.querySelectorAll("[data-t-placeholder]"))
    el.placeholder = t(el.dataset.tPlaceholder);
  // Dynamic re-renders that were built pre-switch.
  if (findings.length) {
    applyFilter();
    if (selectedIdx >= 0 && selectedIdx < findings.length) renderEvidence(findings[selectedIdx]);
    else renderEvidence(null);
    // Refresh activity + summary counters (they read t() at render time).
    const env = window.__lastEnvelope;
    if (env) { renderActivity(env.activity || []); renderSummary(env.summary); }
  }
}

document.querySelectorAll("#lang-mode button").forEach(btn =>
  btn.addEventListener("click", () => applyLang(btn.dataset.lang)));

try {
  const stored = localStorage.getItem("cockpit.lang");
  if (stored && STRINGS[stored]) lang = stored;
  else if ((navigator.language || "").toLowerCase().startsWith("ko")) lang = "ko";
} catch {}
applyLang(lang);

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function render(envelope, freshIds) {
  window.__lastEnvelope = envelope;
  if (!modeAutoPicked) {
    modeAutoPicked = true;
    if (envelope.has_baseline === false) setBaselineMode("all");
  }
  document.getElementById("repo").textContent = envelope.repo;
  renderSummary(envelope.summary);

  findings = [...envelope.findings].sort((a, b) =>
    (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) ||
    a.file.localeCompare(b.file) ||
    a.span[0] - b.span[0]);

  const rowsEl = document.getElementById("rows");
  rowsEl.innerHTML = "";
  findings.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.className = "finding sev-" + f.severity
      + (freshIds.has(f.id) ? " fresh" : "")
      + (f.baselined ? " baselined" : "");
    tr.dataset.i = i;
    tr.innerHTML = `
      <td><span class="sev ${f.severity}">${t(f.severity)}</span></td>
      <td class="loc"><span class="trace-src" data-trace-kind="file" data-trace-value="${esc(f.file)}">${esc(f.file)}</span>:${f.span[0]}${f.symbol ? " · " + esc(f.symbol) : ""}</td>
      <td class="ana"><span class="trace-src" data-trace-kind="analyzer" data-trace-value="${esc(f.analyzer_id)}">${esc(f.analyzer_id)}</span><br><span style="opacity:0.6">v${esc(f.analyzer_version)}</span></td>
      <td>${esc(f.message)}</td>`;
    rowsEl.appendChild(tr);
    tr.addEventListener("click", () => select(i));
  });
  renderChart(envelope.analyzer_counts || []);
  renderActivity(envelope.activity || []);
  applyFilter();
  renderTraceBar();
  if (selectedIdx >= 0 && selectedIdx < findings.length) {
    renderEvidence(findings[selectedIdx]);
  } else {
    renderEvidence(null);
  }
}

function renderSummary(s) {
  const sumEl = document.getElementById("summary");
  sumEl.innerHTML = "";
  for (const sev of ["block", "warn", "info"]) {
    const n = s[sev] || 0;
    const span = document.createElement("span");
    span.className = "n-" + (n === 0 ? "zero" : sev);
    span.textContent = `${t(sev)} ${n}`;
    sumEl.appendChild(span);
  }
  const files = document.createElement("span");
  files.className = "n-zero";
  files.textContent = `· ${s.files_scanned} ${t("files")}`;
  sumEl.appendChild(files);
}

function renderEvidence(f) {
  const body = document.getElementById("evidence-body");
  if (!f) {
    body.innerHTML = `<div class="evidence-empty">${t("evidence_empty_html")}</div>`;
    return;
  }
  const evJson = JSON.stringify(f.evidence, null, 2);
  const snippet = (f.evidence && (f.evidence.snippet || f.evidence.text)) || evJson;
  const matches = (f.evidence && Array.isArray(f.evidence.matches)) ? f.evidence.matches : [];
  const matchesHtml = matches.length
    ? `<section><h3>${t("matches")} (${matches.length})</h3><div class="matches">`
        + matches.map(m => `<a>${esc(m.file || "")}:${m.span ? m.span[0] : ""}</a>`).join("")
        + `</div></section>`
    : "";
  const rationale = lang === "ko" && f.rationale_ko ? f.rationale_ko : f.rationale;
  body.innerHTML = `<div class="ev">
    <div class="loc"><span class="sev ${f.severity}">${t(f.severity)}</span> <span class="trace-src" data-trace-kind="file" data-trace-value="${esc(f.file)}">${esc(f.file)}</span>:${f.span[0]}${f.symbol ? " · " + esc(f.symbol) : ""}${f.baselined ? ` <span style="color:var(--muted);font-size:0.75rem;">· ${t("baseline_tag")}</span>` : ""}</div>
    <div class="rule"><span class="trace-src" data-trace-kind="analyzer" data-trace-value="${esc(f.analyzer_id)}">${esc(f.analyzer_id)}</span> v${esc(f.analyzer_version)}</div>
    <div class="msg">${esc(f.message)}</div>
    ${rationale ? `<section><h3>${t("how_detected")}</h3><div style="color:var(--muted);font-size:0.83rem;">${esc(rationale)}</div></section>` : ""}
    <section><h3>${t("snippet")}</h3><pre>${esc(snippet)}</pre></section>
    ${matchesHtml}
    <section><h3>${t("raw_evidence")}</h3><pre>${esc(evJson)}</pre></section>
  </div>`;
}

function renderChart(rows) {
  const el = document.getElementById("chart");
  if (!rows.length) { el.innerHTML = `<div class="chart-empty">${t("no_findings")}</div>`; return; }
  const max = Math.max(...rows.map(r => r.total));
  el.innerHTML = rows.map(r => {
    const pct = s => `${(r[s] / max * 100).toFixed(1)}%`;
    const hit = matchesTrace("analyzer", r.id);
    const cls = trace ? (hit ? "chart-row trace-hit" : "chart-row dim") : "chart-row";
    return `<div class="${cls}">
      <span class="name trace-src" data-trace-kind="analyzer" data-trace-value="${esc(r.id)}" title="${esc(r.id)}">${esc(r.id)}</span>
      <span class="bar">
        ${r.block ? `<span class="block" style="width:${pct('block')}"></span>` : ""}
        ${r.warn  ? `<span class="warn"  style="width:${pct('warn')}"></span>`  : ""}
        ${r.info  ? `<span class="info"  style="width:${pct('info')}"></span>`  : ""}
      </span>
      <span class="n">${r.total}</span>
    </div>`;
  }).join("");
}

function renderActivity(rows) {
  const el = document.getElementById("activity");
  if (!rows.length) { el.innerHTML = `<div class="chart-empty">${t("waiting")}</div>`; return; }
  el.innerHTML = rows.map(a => {
    const parts = [];
    if (a.new) parts.push(`<span class="delta pos">+${a.new}</span>`);
    if (a.gone) parts.push(`<span class="delta neg">−${a.gone}</span>`);
    const delta = parts.length ? parts.join(" ") : `<span style="opacity:0.5">·</span>`;
    return `<div class="row">
      <span>${esc(a.at)}</span>
      <span>${a.total} ${t("activity_findings")} · ${a.files} ${t("activity_files")}</span>
      <span>${delta}</span>
    </div>`;
  }).join("");
}

function applyFilter() {
  const showBlock = document.getElementById("f-block").checked;
  const showWarn = document.getElementById("f-warn").checked;
  const showInfo = document.getElementById("f-info").checked;
  const q = document.getElementById("q").value.toLowerCase().trim();
  let shown = 0;
  document.querySelectorAll("tr.finding").forEach((tr, i) => {
    const f = findings[i];
    const sevOk = (f.severity === "block" && showBlock) ||
                  (f.severity === "warn" && showWarn) ||
                  (f.severity === "info" && showInfo);
    const bOk = baselineMode === "all" ||
                (baselineMode === "new" && !f.baselined) ||
                (baselineMode === "baselined" && f.baselined);
    const qOk = !q || tr.textContent.toLowerCase().includes(q);
    const visible = sevOk && bOk && qOk;
    tr.classList.toggle("hidden", !visible);
    // Trace acts as highlight, not filter — non-matches dim, matches glow.
    const traceHit = findingMatchesTrace(f);
    tr.classList.toggle("dim", !!trace && !traceHit);
    tr.classList.toggle("trace-hit", !!trace && traceHit);
    if (visible) shown++;
  });
  document.getElementById("count").textContent = `${shown} ${t("of")} ${findings.length}`;
  document.getElementById("empty").hidden = shown > 0;
  if (selectedIdx >= 0) {
    const cur = document.querySelector(`tr.finding[data-i="${selectedIdx}"]`);
    if (!cur || cur.classList.contains("hidden")) select(nextVisible(-1, +1));
  }
  renderTraceBar();  // hit-count refreshes with filter changes
}

function nextVisible(from, dir) {
  const rows = [...document.querySelectorAll("tr.finding:not(.hidden)")];
  if (rows.length === 0) return -1;
  const idxs = rows.map(r => +r.dataset.i);
  if (from < 0) return dir > 0 ? idxs[0] : idxs[idxs.length - 1];
  const here = idxs.indexOf(from);
  if (here === -1) return dir > 0 ? idxs[0] : idxs[idxs.length - 1];
  const next = here + dir;
  return idxs[Math.max(0, Math.min(idxs.length - 1, next))];
}

function select(i) {
  document.querySelectorAll("tr.finding.selected").forEach(r => r.classList.remove("selected"));
  selectedIdx = i;
  if (i < 0 || i >= findings.length) { renderEvidence(null); return; }
  const tr = document.querySelector(`tr.finding[data-i="${i}"]`);
  if (tr) {
    tr.classList.add("selected");
    tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  renderEvidence(findings[i]);
}

function setBaselineMode(mode) {
  if (!BASELINE_MODES.includes(mode)) return;
  baselineMode = mode;
  document.querySelectorAll("#baseline-mode button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
  applyFilter();
}

document.querySelectorAll("#baseline-mode button").forEach(btn =>
  btn.addEventListener("click", () => setBaselineMode(btn.dataset.mode)));

const help = document.getElementById("help");
document.getElementById("help-btn").addEventListener("click", () => help.hidden = !help.hidden);
help.addEventListener("click", e => { if (e.target === help) help.hidden = true; });

document.addEventListener("keydown", e => {
  const q = document.getElementById("q");
  if (e.key === "Escape") {
    if (!help.hidden) { help.hidden = true; return; }
    if (trace) { clearTrace(); return; }
    if (document.activeElement === q) { q.blur(); return; }
  }
  if (document.activeElement === q) return;  // typing in search — let it be
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "j": select(nextVisible(selectedIdx, +1)); e.preventDefault(); break;
    case "k": select(nextVisible(selectedIdx, -1)); e.preventDefault(); break;
    case "Enter": case " ": {
      // Nav-to-first if nothing selected; otherwise re-focus the evidence pane's snippet.
      if (selectedIdx < 0) { select(nextVisible(-1, +1)); e.preventDefault(); }
      break;
    }
    case "1": document.getElementById("f-block").click(); break;
    case "2": document.getElementById("f-warn").click(); break;
    case "3": document.getElementById("f-info").click(); break;
    case "n": {
      const i = BASELINE_MODES.indexOf(baselineMode);
      setBaselineMode(BASELINE_MODES[(i + 1) % BASELINE_MODES.length]);
      break;
    }
    case "/": q.focus(); q.select(); e.preventDefault(); break;
    case "?": help.hidden = !help.hidden; break;
  }
});

for (const id of ["f-block", "f-warn", "f-info"]) {
  document.getElementById(id).addEventListener("change", applyFilter);
}
document.getElementById("q").addEventListener("input", applyFilter);

const SYS_PHASES = ["starting", "idle", "debouncing", "scanning", "emitting"];
const SYS_NODE_X = [80, 240, 400, 560, 720];
const SYS_NODE_Y = 60;
const SYS_NODE_R = 22;
const SYS_STRIP_X = 820;
const SYS_STRIP_W = 740;
let sysLastVersion = -1;

function currentAnalyzerFromEvents(events) {
  // Latest event of shape "analyze <id>" wins.
  for (const e of events || []) {
    if (e.phase === "scanning" && typeof e.detail === "string" && e.detail.startsWith("analyze ")) {
      return e.detail.slice(8).trim();
    }
  }
  return null;
}

function renderSystem(sys, envTimings, envErrors) {
  const phase = sys.phase || "idle";
  const phaseIdx = Math.max(0, SYS_PHASES.indexOf(phase));
  const elapsed = sys.phase_elapsed_ms || 0;
  const stuck = elapsed > 30000;
  const threads = sys.threads || [];
  const errIndex = envErrors ? envErrors.index_total || 0 : 0;
  const errAna = envErrors ? (envErrors.analyzer || []).length : 0;

  // ---- stats header ----
  const threadClass = errIndex || errAna ? "red" : (threads.length > 8 ? "amber" : "");
  document.getElementById("sys-stats").innerHTML = `
    <span><span class="k">${t("sys_version_short")}</span><span class="v">${sys.version}</span></span>
    <span><span class="k">${t("sys_uptime_short")}</span><span class="v">${sys.uptime_s}s</span></span>
    <span><span class="k">${t("sys_waiters_short")}</span><span class="v">${sys.waiters}</span></span>
    <span class="spacer"></span>
    <span title="${threads.map(x=>x.name+(x.alive?' ●':' ○')).join(' · ')}">
      <span class="thread-dot ${threadClass}"></span><span class="v">${threads.length}</span> <span class="k">${t("sys_threads_short")}</span>
    </span>
    ${errIndex ? `<span><span class="k">${t("sys_idx_err")}</span><span class="v warn">${errIndex}</span></span>` : ""}
    ${errAna ? `<span><span class="k">${t("sys_ana_err")}</span><span class="v warn">${errAna}</span></span>` : ""}
  `;

  // ---- SVG: state spine ----
  const svg = document.getElementById("sys-svg");
  const parts = [];
  // Connectors between nodes.
  for (let i = 0; i < SYS_NODE_X.length - 1; i++) {
    const cls = i < phaseIdx ? "connector done" : "connector";
    parts.push(`<line class="${cls}" x1="${SYS_NODE_X[i] + SYS_NODE_R}" y1="${SYS_NODE_Y}" x2="${SYS_NODE_X[i+1] - SYS_NODE_R}" y2="${SYS_NODE_Y}"/>`);
  }
  // Nodes.
  for (let i = 0; i < SYS_NODE_X.length; i++) {
    const isCurrent = i === phaseIdx;
    const isDone = i < phaseIdx;
    const hasErr = isCurrent && phase === "scanning" && errIndex > 0;
    const cls = ["node"];
    if (isDone) cls.push("done");
    if (isCurrent) cls.push("current");
    if (isCurrent && stuck) cls.push("stuck");
    if (hasErr) cls.push("err");
    const x = SYS_NODE_X[i];
    parts.push(`<circle class="${cls.join(' ')}" cx="${x}" cy="${SYS_NODE_Y}" r="${SYS_NODE_R}"/>`);

    // Pulse ring around current.
    if (isCurrent) {
      parts.push(`<circle class="pulse${stuck ? ' stuck' : ''}" cx="${x}" cy="${SYS_NODE_Y}" r="22"/>`);
      // Progress ring — dashoffset based on (elapsed % 2000) / 2000
      const circ = 2 * Math.PI * 28;
      const frac = (elapsed % 2000) / 2000;
      const off = circ * (1 - frac);
      parts.push(`<circle class="ring" cx="${x}" cy="${SYS_NODE_Y}" r="28" stroke-dasharray="${circ.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}"/>`);
    }
    // Label + elapsed.
    parts.push(`<text class="label${isCurrent ? ' current' : ''}" x="${x}" y="${SYS_NODE_Y + SYS_NODE_R + 18}">${esc(t("phase_" + SYS_PHASES[i]))}${isCurrent && stuck ? esc(t("phase_stuck_suffix")) : ""}</text>`);
    if (isCurrent) {
      const secs = elapsed >= 1000 ? (elapsed / 1000).toFixed(1) + "s" : elapsed + "ms";
      parts.push(`<text class="elapsed" x="${x}" y="${SYS_NODE_Y + SYS_NODE_R + 34}">${secs}</text>`);
    }
  }

  // ---- Analyzer pips under 'scanning' node (index 3, x=560) ----
  const scanX = SYS_NODE_X[3];
  const pipY = SYS_NODE_Y + SYS_NODE_R + 48;
  // Canonical analyzer order: prefer envTimings, else derive from events.
  let analyzerIds = [];
  if (envTimings && envTimings.analyzers) {
    analyzerIds = envTimings.analyzers.map(a => a.id);
  }
  const currentAnalyzer = phase === "scanning" ? currentAnalyzerFromEvents(sys.events) : null;
  if (analyzerIds.length) {
    const spacing = 12;
    const startX = scanX - ((analyzerIds.length - 1) * spacing) / 2;
    let hitCurrent = false;
    for (let i = 0; i < analyzerIds.length; i++) {
      const id = analyzerIds[i];
      let cls = "pip";
      if (phase === "scanning" && currentAnalyzer) {
        if (id === currentAnalyzer) { cls += " active"; hitCurrent = true; }
        else if (!hitCurrent) cls += " done";
      } else if (phase === "idle" || phase === "emitting") {
        cls += " done";
      }
      if (trace) cls += matchesTrace("analyzer", id) ? "" : " dim";
      parts.push(`<circle class="${cls}" cx="${startX + i * spacing}" cy="${pipY}" r="3.5" data-trace-kind="analyzer" data-trace-value="${esc(id)}"><title>${esc(id)}</title></circle>`);
    }
  }

  // ---- Timing strip (right region) ----
  const stripFresh = envTimings && sys.version !== sysLastVersion;
  if (envTimings && envTimings.analyzers && envTimings.analyzers.length) {
    const total = envTimings.total_ms || 1;
    const header = `${envTimings.total_ms}ms ${t("sys_timing_total")} · ${envTimings.index_ms}ms ${t("sys_timing_index")} · ${envTimings.changeset_ms}ms ${t("sys_timing_changeset")}`;
    parts.push(`<text class="tim-hdr" x="${SYS_STRIP_X}" y="26" text-anchor="start">${esc(header)}</text>`);
    const barY = 44, barH = 28;
    let cursor = SYS_STRIP_X;
    const gClass = stripFresh ? "strip-in" : "";
    parts.push(`<g class="${gClass}">`);
    for (const a of envTimings.analyzers) {
      const w = Math.max(2, (a.ms / total) * SYS_STRIP_W);
      let fill = "var(--info)";
      if (a.ms >= 200 && a.findings > 0 && a.ms >= 500) fill = "var(--block)";
      else if (a.ms >= 200) fill = "var(--warn)";
      else if (a.ms >= 50) fill = "var(--live)";
      const errCls = errAna && a.ms === 0 ? " err" : "";
      const trClass = trace ? (matchesTrace("analyzer", a.id) ? " trace-hit" : " dim") : "";
      parts.push(`<rect class="tim-seg${errCls}${trClass}" x="${cursor.toFixed(2)}" y="${barY}" width="${(w - 1).toFixed(2)}" height="${barH}" fill="${fill}" data-trace-kind="analyzer" data-trace-value="${esc(a.id)}"><title>${esc(a.id)} - ${a.ms}ms - ${a.findings} findings</title></rect>`);
      // Label if segment is wide enough (>=44 viewbox units).
      if (w >= 44) {
        const short = a.id.split(".").slice(-1)[0];
        parts.push(`<text class="tim-label" x="${(cursor + w / 2).toFixed(2)}" y="${barY + barH + 12}">${esc(short)}</text>`);
      }
      cursor += w;
    }
    parts.push(`</g>`);
    sysLastVersion = sys.version;
  } else {
    parts.push(`<text class="tim-empty" x="${SYS_STRIP_X + SYS_STRIP_W / 2}" y="72">${esc(t("sys_waiting"))}</text>`);
  }

  svg.innerHTML = parts.join("");
}

async function pollSystem() {
  while (true) {
    try {
      const r = await fetch("/system.json");
      const sys = await r.json();
      window.__lastSys = sys;
      const env = window.__lastEnvelope;
      renderSystem(sys, env ? env.timings : null, env ? env.errors : null);
    } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
}
pollSystem();

async function poll() {
  const dot = document.getElementById("dot");
  const label = document.getElementById("livetext");
  while (true) {
    try {
      const r = await fetch(`/state.json?since=${version}`);
      const { version: v, envelope, scanning } = await r.json();
      dot.classList.toggle("scanning", scanning);
      dot.classList.remove("stale");
      label.textContent = scanning ? t("scanning") : t("live");
      if (envelope && v !== version) {
        version = v;
        const newIds = new Set(envelope.findings.map(f => f.id));
        const fresh = new Set([...newIds].filter(id => !prevIds.has(id)));
        prevIds = newIds;
        render(envelope, fresh);
      }
    } catch (e) {
      dot.classList.add("stale");
      label.textContent = t("disconnected");
      await new Promise(r => setTimeout(r, 2000));
    }
  }
}
poll();
</script>
"""


def demo() -> None:
    """Self-check: start server on ephemeral port, hit /state.json, stop."""
    import socket
    import tempfile
    import urllib.request
    from contextlib import closing

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("def f():\n    try: x()\n    except: pass\n")
        with closing(socket.socket()) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        t = threading.Thread(target=_watch_loop, args=(root,), daemon=True)
        t.start()
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        st = threading.Thread(target=server.serve_forever, daemon=True)
        st.start()
        try:
            # Wait for first envelope.
            for _ in range(50):
                r = urllib.request.urlopen(f"http://127.0.0.1:{port}/state.json?since=-1", timeout=3)
                data = json.loads(r.read())
                if data["envelope"] is not None:
                    break
                time.sleep(0.1)
            assert data["envelope"] is not None, "no envelope after 5s"
            assert data["envelope"]["schema"] == 1
            # Page renders.
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
            assert "cockpit" in page and "state.json" in page
            print("serve ok")
        finally:
            server.shutdown()


if __name__ == "__main__":
    demo()
