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
import dataclasses
import datetime
import functools
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


@dataclasses.dataclass
class ServeContext:
    """Owns the per-server-instance mutable state (scan state, scanner
    cache, DNS-rebinding allowlist). Backend senior review flagged the
    three module-level singletons as arch debt. This wraps them into one
    object so tests can spin up an isolated context, and so a future
    multi-tenant serve (multiple repos in one process) becomes possible
    without a rewrite.

    Backward-compat aliases (`_state`, `_scanner`, `_ALLOWED_HOSTS`) still
    point at `_default_ctx` fields — existing tests and integrations keep
    working. New callers should pass `ctx=` explicitly."""
    state: "_State" = dataclasses.field(default_factory=lambda: _State())
    scanner: IncrementalScanner = dataclasses.field(default_factory=IncrementalScanner)
    allowed_hosts: set[str] = dataclasses.field(default_factory=set)


def new_context() -> ServeContext:
    """Fresh, isolated context. Prefer this in tests over monkeypatching
    the module singletons."""
    return ServeContext()


_default_ctx = ServeContext()
_state = _default_ctx.state


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


_scanner = _default_ctx.scanner


def _scan(repo: Path, force_full: bool = False, ctx: ServeContext | None = None) -> dict:
    """Wrap incremental scan with baseline + rationale annotations."""
    ctx = ctx or _default_ctx
    env = ctx.scanner.scan(repo, force_full=force_full, set_phase=ctx.state.set_phase)
    # Best-effort persistence: dump the caches so the next process start
    # skips the cold scan. Silent on failure — never blocks the watch loop.
    ctx.scanner.save(repo)

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


def _watch_loop(repo: Path, ctx: ServeContext | None = None) -> None:
    """Watch the repo forever. Any exception inside a scan is logged and
    the loop continues — a crashed scan must never wedge the UI into
    perpetual "scanning…" (previous versions did exactly that)."""
    ctx = ctx or _default_ctx
    def _safe_scan(force_full: bool = False) -> None:
        ctx.state.set_scanning(True)
        try:
            ctx.state.set(_scan(repo, force_full=force_full, ctx=ctx))
        except Exception:
            print("cockpit serve: scan failed:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        finally:
            ctx.state.set_scanning(False)
            ctx.state.set_phase("idle")

    # Warm-start from `.cockpit/state/` if it survived a previous run.
    # load() is silent on miss/corrupt so it never blocks cold scan.
    warm = ctx.scanner.load(repo)
    ctx.state.set_phase("scanning", "warm resume" if warm else "cold start")
    _safe_scan(force_full=not warm)

    prev = _snapshot(repo)
    last_change_at: float | None = None
    while True:
        try:
            time.sleep(POLL_INTERVAL)
            cur = _snapshot(repo)
            if cur != prev:
                changed = _changed_paths(prev, cur)
                ctx.state.set_phase("debouncing",
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
_ALLOWED_HOSTS: set[str] = _default_ctx.allowed_hosts   # populated by cmd_serve


class _Handler(BaseHTTPRequestHandler):
    # Handler class overrides set this to a specific ServeContext; the
    # default handler falls back to `_default_ctx` for backward compat.
    _ctx: "ServeContext | None" = None
    # Kill slowloris — a client that opens a socket and never sends bytes
    # will otherwise hold a thread until TCP FIN.
    timeout = 15

    # Drop the "Server: BaseHTTP/0.6 Python/3.11.x" fingerprint.
    def version_string(self) -> str:
        return "cockpit"

    def log_message(self, format: str, *args) -> None:
        pass  # ponytail: silence per-request access log

    def _get_ctx(self) -> "ServeContext":
        return self._ctx or _default_ctx

    def _host_ok(self) -> bool:
        """Reject requests with a Host header outside the allowlist.
        DNS-rebinding defense: an external site can otherwise coerce
        the browser into fetching http://127.0.0.1:port under its own
        origin and reading source snippets."""
        host = (self.headers.get("Host") or "").strip().lower()
        allowlist = self._get_ctx().allowed_hosts
        if not allowlist:
            return True   # allowlist not configured — off by default
        return host in allowlist

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send(400, "text/plain", b"host header rejected")
            return
        try:
            url = urlparse(self.path)
        except ValueError:
            self._send(400, "text/plain", b"bad url")
            return
        state = self._get_ctx().state
        if url.path == "/":
            strings_json = json.dumps(_STRINGS, ensure_ascii=False)
            # Belt-and-suspenders against payload closing the injecting script tag.
            strings_json = strings_json.replace("</", "<\\/")
            page = _load_page().replace("__STRINGS_JSON__", strings_json)
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif url.path == "/state.json":
            try:
                since = int((parse_qs(url.query).get("since") or ["-1"])[0])
            except (ValueError, TypeError):
                self._send(400, "application/json",
                           b'{"error":"bad since"}')
                return
            if state.waiters >= MAX_WAITERS:
                self._send(503, "application/json",
                           b'{"error":"too many waiters"}')
                return
            version, envelope, scanning = state.wait_after(since, WAIT_TIMEOUT)
            body = json.dumps({
                "version": version,
                "envelope": envelope,
                "scanning": scanning,
                "system": state.snapshot_system(),
            }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body)
        elif url.path == "/system.json":
            body = json.dumps(state.snapshot_system(), ensure_ascii=False).encode("utf-8")
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


def _make_handler(ctx: ServeContext) -> type[_Handler]:
    """Bind a ServeContext into a per-server handler subclass. Each
    `cmd_serve` (or test) can spawn an isolated handler tied to its
    own state/scanner/allowlist without touching module globals."""
    class BoundHandler(_Handler):
        pass
    BoundHandler._ctx = ctx
    return BoundHandler


def cmd_serve(repo: Path, port: int = 8765, host: str = "127.0.0.1",
              ctx: ServeContext | None = None) -> int:
    ctx = ctx or _default_ctx
    t = threading.Thread(target=_watch_loop, args=(repo,), kwargs={"ctx": ctx},
                         daemon=True)
    t.start()

    # Populate Host-header allowlist for DNS-rebinding defense.
    ctx.allowed_hosts.clear()
    ctx.allowed_hosts.update({
        f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}",
        f"127.0.0.1", "localhost", "[::1]",
    })
    if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::"):
        ctx.allowed_hosts.update({f"{host}:{port}", host})

    httpd = ThreadingHTTPServer((host, port), _make_handler(ctx))
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


# The dashboard's HTML/JS/CSS lives in `static/index.html` — a Backend
# senior review flagged the 800-line embedded string as an editing/lint
# hazard. Loaded once, cached via functools.lru_cache.
@functools.lru_cache(maxsize=1)
def _load_page() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


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
