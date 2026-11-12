#!/usr/bin/env python3
"""check_011 - local mock UI gate for work order 011.

Written before the workbench UI. G1-G11 are expected red until
workbench/serve_local.py and the four workbench/ui files exist. G12
re-runs check_010 on this same tree and must stay green.

Stdlib only, offline, ASCII stdout. The live tree is read only.
Mutations are appended on a temp copy. Every child gets
PYTHONIOENCODING=utf-8 and PYTHONDONTWRITEBYTECODE=1, has PYTHONPATH
removed, then PYTHONPATH set to workbench.

R2 labels and the R3 shape are constants here. This script does not
read the spec while it runs.

Each check prints [PASS], [FAIL], or [BLOCKED]. Exit 0 only when every
one is PASS. BLOCKED means the interpreter did not start or a temp copy
could not be made. A missing implementation file is FAIL.
"""

import os
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import ast
import copy
import hashlib
import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

SERVE_REL = "workbench/serve_local.py"
HTML_REL = "workbench/ui/index.html"
JS_REL = "workbench/ui/app.js"
CSS_REL = "workbench/ui/style.css"
JOBS_REL = "workbench/ui/fixtures/jobs.json"
STOP_REL = "workbench/stop_policy.py"
SCENARIO_REL = "workbench/fixtures/scenarios.json"
PRODUCT_RELS = (HTML_REL, JS_REL, CSS_REL, JOBS_REL, SERVE_REL)

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
FAILURES = []

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)
HASH_SKIP = {".git", "__pycache__"}
COPY_SKIP = {".git", "__pycache__", ".venv", "venv"}

ALLOWED_IMPORTS = frozenset({
    "argparse", "copy", "http.server", "json", "pathlib", "socketserver",
    "sys", "urllib.parse", "stop_policy",
})
BANNED_CALLS = frozenset({"open", "eval", "exec", "compile", "__import__"})
BANNED_ATTRS = frozenset({
    "write_text", "write_bytes", "mkdir", "unlink", "rename", "touch",
})
BANNED_ADDR = frozenset({"0.0.0.0", "localhost", "::"})
NEED_FUNCS = ("state_view", "load_state", "handle", "main")
NEED_DATA = ("HOST", "STATE_LABELS", "BUSY_STATES")

STATE_CODES = (
    "REGISTERED", "QUEUED", "STARTING", "RUNNING", "SAVING", "COLLECTING",
    "RELEASING", "RELEASE_UNCONFIRMED", "PAUSED", "RECONCILING", "UNKNOWN",
    "BLOCKED", "DONE", "FAILED", "CANCELLED",
)
STATE_LABELS = {
    "REGISTERED": "已登記",
    "QUEUED": "排隊中",
    "STARTING": "準備中",
    "RUNNING": "執行中",
    "SAVING": "保存中",
    "COLLECTING": "收產出中",
    "RELEASING": "釋放中",
    "RELEASE_UNCONFIRMED": "釋放未確認",
    "PAUSED": "已暫停",
    "RECONCILING": "核對中",
    "UNKNOWN": "狀態不明",
    "BLOCKED": "需要你處理",
    "DONE": "完成",
    "FAILED": "失敗",
    "CANCELLED": "已取消",
}
BUSY_STATES = frozenset({
    "STARTING", "RUNNING", "SAVING", "COLLECTING", "RELEASING",
    "RELEASE_UNCONFIRMED", "RECONCILING", "UNKNOWN", "BLOCKED",
})
TERMINAL_STATES = frozenset({"DONE", "FAILED", "CANCELLED"})
HOST_LABELS = {
    "online": "在線",
    "shutting_down": "即將關機",
    "just_booted": "剛開機核對中",
}
DECISION_KEYS = (
    "action", "next_state", "reason_code", "ui_message", "data_at_risk",
    "notify_human", "human_hold_after", "stop_intent", "from_unit",
)
SUMMARY_KEYS = (
    "job_id", "title", "job_type", "state", "state_label", "busy", "terminal",
    "submitted_by", "submitter_label", "human_hold", "progress", "cu",
    "release_label", "decision", "decision_error", "blocker",
)
CU_KEYS = (
    "used", "soft", "cap", "balance", "rate_per_hour", "minutes_to_cap", "notice",
)
ACTION_CODES = (
    "CONTINUE", "WAIT", "REQUEST_SAVE", "COLLECT", "RELEASE", "RECHECK_RELEASE",
    "RECONCILE", "MARK_UNKNOWN", "ESCALATE", "REJECT_REQUEST", "CLOSE",
)
COMMANDS = ("stop_after_save", "pause", "resume", "stop_now")
JOB_KEYS = {"now", "snapshot", "contract", "policy", "display"}
DISPLAY_KEYS = {
    "title", "progress_total", "cu_balance", "cu_rate_per_hour", "note",
    "files", "timeline",
}
FILE_KEYS = {"name", "size_bytes", "sha256_8", "verify", "landed"}
TIMELINE_KEYS = {"at", "from", "to", "by"}
TOP_KEYS = {"schema", "notice", "host", "jobs"}
NOTICE = "示意數字，非真實額度"
AUDIT_KEYS = ("at", "caller", "action", "job_id", "result")
BOT_KEYS = {
    "list_jobs": {"ok", "jobs"},
    "get_status": {
        "ok", "job_id", "state", "state_label", "progress", "reason_code", "ui_message",
    },
    "request_pause": {"ok", "job_id", "accepted", "reason_code"},
    "submit_job": {"ok", "accepted", "reason_code"},
}
LIST_ROW_KEYS = {"job_id", "state", "state_label", "progress", "reason_code"}
APPLY_KEYS = {"job_id", "accepted", "decision", "job"}
FORBIDDEN_BODY_KEYS = {"timeline", "audit", "files", "contract_summary"}
DISALLOWED_ACTIONS = (
    "resume", "stop_now", "release", "unlock", "set_cap", "read_file", "exec", "",
)
NOT_FOUND_PATHS = (
    "/../serve_local.py",
    "/fixtures/jobs.json",
    "/ui/fixtures/jobs.json",
    "/serve_local.py",
    "/stop_policy.py",
    "/api/jobs/no-such-job",
    "/api/nope",
)
STATIC_CASES = (
    ("/", "index.html"),
    ("/index.html", "index.html"),
    ("/app.js", "app.js"),
    ("/style.css", "style.css"),
)
SECTIONS = (
    ("section-job-list", "任務列表"),
    ("section-job-detail", "任務詳情"),
    ("section-blocker", "阻塞原因"),
    ("section-cu", "CU 面板"),
    ("section-outputs", "產出與雜湊"),
    ("section-release", "釋放狀態"),
    ("section-stop", "停止"),
    ("section-host", "本機狀態"),
    ("section-onboarding", "首次引導"),
)
STOP_BUTTONS = (
    ("btn-stop-after-save", "保存後停止（建議）"),
    ("btn-stop-now", "立即停止（可能遺失未保存產出）"),
)
ONBOARDING = ("看列表", "看阻塞原因", "怎麼停")
BANNED_JS = (
    "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "import(",
    "eval(", "new Function", "document.cookie", "localStorage", "sessionStorage",
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
)
VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
})
SENTINEL = "gate-sentinel-011"
LISTENING_RE = re.compile(r"^LISTENING 127\.0\.0\.1 (\d+)$")
JOB_ID_RE = re.compile(r"^demo-(J1|J3|WAN)-(\d{3})$")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
SHA8_RE = re.compile(r"^[0-9a-f]{8}$")
FETCH_ANY_RE = re.compile(r"fetch\(")
FETCH_API_RE = re.compile(r"""fetch\(\s*['"`]/api/""")
URL_RE = re.compile(r"https?://", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Filesystem prefixes only. /api/ routes and /index.html are not paths.
FS_ABS_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])/(?:home|Users|tmp|etc|workspace|mnt)(?:/|[^A-Za-z0-9_]|$)"
)
DRIVE_RE = re.compile(r"(?:^|[^A-Za-z0-9_])[A-Za-z]:[\\/]")
PROTO_REL_RE = re.compile(r"""['"`]//[A-Za-z0-9]""")
TOKEN_RES = (
    ("github token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("key token", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws token", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("assigned secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|refresh[_-]?token|password)\b"
        r"\s*[:=]\s*['\"][^'\"]{6,}['\"]"
    )),
    ("bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
)

S1_SRC = """\
_gate011_s1 = decide


def decide(snapshot, contract, policy, now):
    result = _gate011_s1(snapshot, contract, policy, now)
    if not isinstance(result, dict):
        return result
    cloned = dict(result)
    cloned["reason_code"] = "GATE_SENTINEL"
    return cloned
"""

S2_SRC = """\
def decide(snapshot, contract, policy, now):
    raise ValueError("gate")
"""

S3_SRC = """\
_gate011_s3 = decide


def decide(snapshot, contract, policy, now):
    result = _gate011_s3(snapshot, contract, policy, now)
    if not isinstance(result, dict):
        return result
    cloned = dict(result)
    cloned["action"] = "CONTINUE"
    cloned["next_state"] = "PAUSED"
    return cloned
"""

MUTANTS = (
    ("S1", S1_SRC),
    ("S2", S2_SRC),
    ("S3", S3_SRC),
)

DRIVER = """
import io
import json
import sys
from pathlib import Path

AUDIT_KEYS = ("at", "caller", "action", "job_id", "result")


def find_audits(obj, found, seen):
    marker = id(obj)
    if marker in seen:
        return
    if isinstance(obj, dict):
        seen.add(marker)
        if set(obj.keys()) == set(AUDIT_KEYS):
            found.append({key: obj[key] for key in AUDIT_KEYS})
            return
        for value in obj.values():
            find_audits(value, found, seen)
    elif isinstance(obj, list):
        seen.add(marker)
        for value in obj:
            find_audits(value, found, seen)


def do_import_probe():
    import socketserver
    real_out = sys.stdout
    real_err = sys.stderr
    cap_out = io.StringIO()
    cap_err = io.StringIO()
    sys.stdout = cap_out
    sys.stderr = cap_err
    binds = []
    orig = socketserver.TCPServer.server_bind

    def wrapped(self):
        binds.append(1)
        return orig(self)

    socketserver.TCPServer.server_bind = wrapped
    import_error = ""
    host = None
    try:
        import serve_local
        host = getattr(serve_local, "HOST", None)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        import_error = type(exc).__name__
    finally:
        sys.stdout = real_out
        sys.stderr = real_err
    return {
        "stdout": cap_out.getvalue(),
        "stderr": cap_err.getvalue(),
        "binds": len(binds),
        "import_error": import_error,
        "host": host,
    }


def do_inspect(payload):
    import serve_local
    views = []
    for code in payload.get("codes") or []:
        views.append(serve_local.state_view(code))
    busy = serve_local.BUSY_STATES
    busy_values = None
    if isinstance(busy, (set, frozenset, list, tuple)):
        busy_values = sorted(list(busy))
    return {
        "host": getattr(serve_local, "HOST", None),
        "labels": serve_local.STATE_LABELS,
        "busy_type": type(busy).__name__,
        "busy": busy_values,
        "views": views,
    }


def do_decide(payload):
    from stop_policy import decide
    items = []
    for item in payload.get("items") or []:
        try:
            result = decide(
                item["snapshot"], item["contract"], item["policy"], item["now"])
            items.append({"ok": True, "result": result})
        except ValueError:
            items.append({"ok": False, "error": "ValueError"})
        except Exception as exc:
            items.append({"ok": False, "error": type(exc).__name__})
    return {"items": items}


def one_call(serve_local, state, call):
    method = call.get("method")
    path = call.get("path")
    body = call.get("body") if "body" in call else None
    try:
        pair = serve_local.handle(state, method, path, body)
    except Exception as exc:
        return {"error": type(exc).__name__}
    if not isinstance(pair, tuple) or len(pair) != 2:
        return {"error": "handle shape"}
    status, got = pair
    if type(status) is not int:
        return {"error": "status type"}
    try:
        json.dumps(got, ensure_ascii=True)
    except (TypeError, ValueError):
        return {"error": "payload not JSON"}
    audits = []
    find_audits(state, audits, set())
    return {"status": status, "payload": got, "audits": audits}


def do_sessions(payload):
    import serve_local
    sessions = []
    for session in payload.get("sessions") or []:
        try:
            state = serve_local.load_state()
        except Exception as exc:
            sessions.append({"error": type(exc).__name__})
            continue
        calls = []
        for call in session.get("calls") or []:
            calls.append(one_call(serve_local, state, call))
        sessions.append({"calls": calls})
    return {"sessions": sessions}


def run(payload):
    mode = payload.get("mode")
    if mode == "import_probe":
        return do_import_probe()
    if mode == "inspect":
        return do_inspect(payload)
    if mode == "decide":
        return do_decide(payload)
    if mode == "sessions":
        return do_sessions(payload)
    return {"error": "bad mode"}


def main():
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + chr(10))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + ": " + str(exc) + chr(10))
        raise SystemExit(1)
"""


def ascii_text(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def one_line(value):
    return ascii_text(value).replace("\r", "\\r").replace("\n", "\\n")


def gate(name, status, detail=""):
    if status not in (PASS, FAIL, BLOCKED):
        status = FAIL
        detail = "bad status " + ascii_text(status) + ("; " + detail if detail else "")
    if status != PASS:
        FAILURES.append(name)
    suffix = " -- " + one_line(detail) if detail else ""
    print("[" + status + "] " + one_line(name) + suffix, flush=True)


def child_env(extra=None):
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "workbench"
    if extra:
        for key, value in extra.items():
            env[str(key)] = str(value)
    return env


def run_process(argv, cwd, timeout=60, extra_env=None):
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(extra_env),
            cwd=str(cwd),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return subprocess.CompletedProcess(argv, 124, stdout, stderr + "\ntimeout")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", type(exc).__name__)


def tail(proc, n=240):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text[-n:]


def cap_text(parts, limit=8):
    if len(parts) <= limit:
        return "; ".join(parts)
    return "; ".join(parts[:limit]) + "; +" + str(len(parts) - limit) + " more"


def missing_rels(rels):
    missing = []
    for rel in rels:
        if not (REPO_ROOT / rel).is_file():
            missing.append(rel)
    return missing


def miss_detail(rels):
    missing = missing_rels(rels)
    if not missing:
        return ""
    return "missing " + ", ".join(missing)


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("non-string key")
        if key in obj:
            raise ValueError("duplicate key " + key)
        obj[key] = value
    return obj


def load_json(rel):
    path = REPO_ROOT / rel
    if not path.is_file():
        return None, "missing " + rel
    try:
        text = read_text(path)
    except (OSError, UnicodeError) as exc:
        return None, rel + " unreadable: " + type(exc).__name__
    try:
        doc = json.loads(text, object_pairs_hook=strict_object)
    except ValueError as exc:
        return None, rel + " " + type(exc).__name__ + ": " + str(exc)[:160]
    return doc, ""


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def same(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        if left == right:
            return True
        scale = max(1.0, abs(float(left)), abs(float(right)))
        return abs(float(left) - float(right)) <= 1e-9 * scale
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(same(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def diff_keys(got, expect, prefix=""):
    if not isinstance(got, dict) or not isinstance(expect, dict):
        return [prefix + "type"]
    if set(got) != set(expect):
        return [prefix + "keys"]
    found = []
    for key in expect:
        path = prefix + key
        if isinstance(expect[key], dict) and isinstance(got.get(key), dict):
            found.extend(diff_keys(got[key], expect[key], path + "."))
        elif not same(got.get(key), expect[key]):
            found.append(path)
    return found


def has_cjk(text):
    for ch in text:
        code = ord(ch)
        if (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
                or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF
                or 0xF900 <= code <= 0xFAFF):
            return True
    return False


def has_key(obj, banned):
    if isinstance(obj, dict):
        if banned & set(obj):
            return True
        return any(has_key(value, banned) for value in obj.values())
    if isinstance(obj, list):
        return any(has_key(value, banned) for value in obj)
    return False


def contains_text(obj, needle):
    try:
        blob = json.dumps(obj, ensure_ascii=True)
    except (TypeError, ValueError):
        blob = str(obj)
    return needle in blob


def error_shape(payload):
    problems = []
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    if set(payload) != {"reason_code", "ui_message"}:
        return ["error keys"]
    code = payload.get("reason_code")
    msg = payload.get("ui_message")
    if not isinstance(code, str) or code == "":
        problems.append("reason_code")
    if not isinstance(msg, str) or msg == "" or not has_cjk(msg):
        problems.append("ui_message")
    blob = json.dumps(payload, ensure_ascii=False)
    for bad in ("Traceback", "Error", "Exception", ".py"):
        if bad in blob:
            problems.append("leaks " + bad)
    return problems


def line_hit(line):
    if URL_RE.search(line) or PROTO_REL_RE.search(line):
        return "url"
    if EMAIL_RE.search(line):
        return "email"
    if FS_ABS_RE.search(line) or DRIVE_RE.search(line):
        return "absolute path"
    for name, pattern in TOKEN_RES:
        if pattern.search(line):
            return name
    return None


def hygiene_hits(rel):
    path = REPO_ROOT / rel
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [rel + " unreadable: " + type(exc).__name__]
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        kind = line_hit(line)
        if kind:
            hits.append(rel + ":" + str(number) + " " + kind)
            if len(hits) >= 8:
                break
    return hits


def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def live_blobs():
    found = {}
    root = REPO_ROOT
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in HASH_SKIP]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                rel = path.relative_to(root).as_posix()
                found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                found[path.as_posix()] = "unreadable"
    return found


def blob_changes(before, after):
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def ignore_noise(_directory, names):
    return [name for name in names if name in COPY_SKIP or name.endswith(".pyc")]


def outside_temp_parent():
    root = REPO_ROOT.resolve()
    seen = set()
    for candidate in (Path(tempfile.gettempdir()), Path("/tmp")):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        try:
            inside = resolved == root or resolved.is_relative_to(root)
        except OSError:
            continue
        if not inside:
            return resolved
    return None


def parse_json_stdout(text):
    body = text[:-1] if text.endswith("\n") else text
    if body.endswith("\r"):
        body = body[:-1]
    if body == "" or "\n" in body or "\r" in body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def launch_driver(root, payload, timeout):
    try:
        compile(DRIVER, "<check011-driver>", "exec")
    except SyntaxError as exc:
        return None, FAIL, "driver does not compile: " + str(exc)
    parent = outside_temp_parent()
    if parent is None:
        return None, BLOCKED, "no directory outside the repo"
    try:
        holder = tempfile.TemporaryDirectory(prefix="check011-", dir=str(parent))
    except OSError as exc:
        return None, BLOCKED, "temp dir " + type(exc).__name__
    with holder:
        script_path = Path(holder.name) / "driver.py"
        payload_path = Path(holder.name) / "payload.json"
        try:
            if script_path.resolve().is_relative_to(REPO_ROOT.resolve()):
                return None, FAIL, "driver landed in the live tree"
            script_path.write_text(DRIVER, encoding="utf-8", newline="\n")
            payload_path.write_text(
                json.dumps(payload, ensure_ascii=True),
                encoding="utf-8",
                newline="\n",
            )
        except (OSError, TypeError, ValueError) as exc:
            return None, BLOCKED, "driver write " + type(exc).__name__
        proc = run_process(
            [sys.executable, str(script_path), str(payload_path)],
            root,
            timeout=timeout,
        )
    return proc, None, ""


def call_driver(root, payload, timeout=60):
    proc, status, detail = launch_driver(root, payload, timeout)
    if proc is None:
        return None, status, detail
    if proc.returncode == 127:
        return None, BLOCKED, "driver could not start tail=" + one_line(tail(proc))
    if proc.returncode == 124:
        return None, FAIL, "driver did not return tail=" + one_line(tail(proc))
    if proc.returncode != 0:
        return None, FAIL, "driver exit " + str(proc.returncode) + " tail=" + one_line(tail(proc))
    data = parse_json_stdout(proc.stdout or "")
    if not isinstance(data, dict):
        return None, FAIL, "driver stdout is not one JSON object tail=" + one_line(tail(proc))
    if data.get("error"):
        return None, FAIL, "driver " + one_line(data.get("error"))
    return data, None, ""


def job_item(job):
    return {
        "snapshot": job["snapshot"],
        "contract": job["contract"],
        "policy": job["policy"],
        "now": job["now"],
    }


def decide_items(root, items):
    data, status, detail = call_driver(root, {"mode": "decide", "items": items}, 60)
    if status:
        return None, status, detail
    got = data.get("items")
    if not isinstance(got, list) or len(got) != len(items):
        return None, FAIL, "decide count"
    return got, None, ""


def run_sessions(root, sessions, timeout=60):
    data, status, detail = call_driver(
        root, {"mode": "sessions", "sessions": sessions}, timeout)
    if status:
        return None, status, detail
    got = data.get("sessions")
    if not isinstance(got, list) or len(got) != len(sessions):
        return None, FAIL, "session count"
    return got, None, ""


def call_of(session, index):
    if not isinstance(session, dict):
        return None, "session shape"
    if session.get("error"):
        return None, "load_state " + str(session.get("error"))
    calls = session.get("calls")
    if not isinstance(calls, list) or index >= len(calls):
        return None, "missing call " + str(index)
    got = calls[index]
    if not isinstance(got, dict):
        return None, "call shape"
    if got.get("error"):
        return None, str(got.get("error"))
    return got, ""


def coverage_job(jobs, kind):
    for job in jobs:
        snap = job.get("snapshot")
        con = job.get("contract")
        if not isinstance(snap, dict) or not isinstance(con, dict):
            continue
        if kind == 3:
            probe = snap.get("probe")
            if (snap.get("state") == "RUNNING"
                    and snap.get("human_hold") is False
                    and snap.get("human_command") == "none"
                    and snap.get("bot_request") == "none"
                    and isinstance(probe, dict)
                    and probe.get("status") == "ok"):
                return job
        elif kind == 4:
            if snap.get("human_hold") is True and con.get("submitted_by") == "bot:demo":
                return job
    return None


def job_id_of(job):
    con = job.get("contract") if isinstance(job, dict) else None
    if isinstance(con, dict) and isinstance(con.get("job_id"), str):
        return con["job_id"]
    return "?"


def expected_view(code):
    if isinstance(code, str) and code in STATE_LABELS:
        return {
            "code": code,
            "label": STATE_LABELS[code],
            "busy": code in BUSY_STATES,
            "terminal": code in TERMINAL_STATES,
        }
    return {"code": code, "label": "狀態不明", "busy": True, "terminal": False}


def expected_release(snapshot):
    state = snapshot.get("state")
    if state == "RELEASE_UNCONFIRMED":
        return "釋放未確認"
    if state == "RELEASING":
        return "釋放中"
    if snapshot.get("release_check") == "confirmed_zero":
        return "已確認 0 active"
    return "無釋放回查"


def expected_blocker(job, decided):
    state = job["snapshot"].get("state")
    dec = decided.get("result") if decided.get("ok") else None
    notify = isinstance(dec, dict) and dec.get("notify_human") is True
    if state not in ("BLOCKED", "RELEASE_UNCONFIRMED", "UNKNOWN") and not notify:
        return None
    note = job["display"].get("note") if isinstance(job.get("display"), dict) else None
    if isinstance(note, str) and note != "":
        message = note
    elif isinstance(dec, dict) and isinstance(dec.get("ui_message"), str) and dec.get("ui_message") != "":
        message = dec["ui_message"]
    else:
        message = "狀態不明，請先核對"
    return {"message": message, "suggested": ["tick", "stop_after_save", "stop_now"]}


def expected_minutes(used, cap, rate):
    # "已超過上限" is used > cap. used == cap still follows the formula (0).
    if rate == 0 or used > cap:
        return None
    return (cap - used) / float(rate) * 60


def expected_summary(notice, job, decided):
    snap = job["snapshot"]
    con = job["contract"]
    disp = job["display"]
    view = expected_view(snap.get("state"))
    if decided.get("ok") and isinstance(decided.get("result"), dict):
        dec = decided["result"]
        derr = None
        busy = view["busy"]
    else:
        dec = None
        derr = "INPUT_INVALID"
        busy = True
    used = snap.get("cu_used")
    cap = con.get("cu_cap")
    rate = disp.get("cu_rate_per_hour")
    ratio = con.get("cu_soft_ratio")
    submitted = con.get("submitted_by")
    if submitted == "human":
        submitter = "人"
    elif isinstance(submitted, str) and submitted.startswith("bot:"):
        submitter = "Bot"
    else:
        submitter = None
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}
    if is_number(ratio) and is_number(cap):
        soft = ratio * cap
    else:
        soft = None
    if is_number(used) and is_number(cap) and is_number(rate):
        minutes = expected_minutes(used, cap, rate)
    else:
        minutes = None
    return {
        "job_id": con.get("job_id"),
        "title": disp.get("title"),
        "job_type": con.get("job_type"),
        "state": snap.get("state"),
        "state_label": view["label"],
        "busy": busy,
        "terminal": view["terminal"],
        "submitted_by": submitted,
        "submitter_label": submitter,
        "human_hold": snap.get("human_hold"),
        "progress": {"value": progress.get("value"), "total": disp.get("progress_total")},
        "cu": {
            "used": used,
            "soft": soft,
            "cap": cap,
            "balance": disp.get("cu_balance"),
            "rate_per_hour": rate,
            "minutes_to_cap": minutes,
            "notice": notice,
        },
        "release_label": expected_release(snap),
        "decision": dec,
        "decision_error": derr,
        "blocker": expected_blocker(job, decided),
    }


def apply_expected(job, decided):
    post = copy.deepcopy(job)
    snap = post["snapshot"]
    if not decided.get("ok"):
        snap["human_command"] = "none"
        snap["bot_request"] = "none"
        return post, True
    result = decided.get("result")
    if not isinstance(result, dict):
        return post, True
    if result.get("action") != "REJECT_REQUEST":
        snap["state"] = result.get("next_state")
        snap["human_hold"] = result.get("human_hold_after")
        snap["stop_intent"] = result.get("stop_intent")
    snap["human_command"] = "none"
    snap["bot_request"] = "none"
    return post, False


def shape_problems(got, expect, path):
    if isinstance(expect, dict):
        if not isinstance(got, dict):
            return [path + " is not an object"]
        if set(got) != set(expect):
            return [path + " keys"]
        found = []
        for key in expect:
            found.extend(shape_problems(got[key], expect[key], path + "." + key))
        return found
    if isinstance(got, (dict, list)):
        return [path + " nested"]
    return []


def module_bindings(tree):
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = value
    return found


def defines_decide(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "decide":
                return True
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "decide":
                    return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "decide":
                return True
        if isinstance(node, ast.ExceptHandler) and node.name == "decide":
            return True
    return False


def imports_decide(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "stop_policy":
            for alias in node.names:
                if alias.name == "decide":
                    return True
    return False


def import_problems(tree):
    problems = []
    seen = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = ["relative"]
            else:
                names = [node.module or ""]
        for name in names:
            if name == "relative":
                issue = "relative import"
            elif name not in ALLOWED_IMPORTS:
                issue = "import " + (name or "?")
            else:
                issue = ""
            if issue and issue not in seen:
                seen.add(issue)
                problems.append(issue)
    return problems


def call_problems(tree):
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
            issue = "calls " + func.id
        elif isinstance(func, ast.Attribute) and func.attr in BANNED_CALLS:
            issue = "calls " + func.attr
        elif isinstance(func, ast.Attribute) and func.attr in BANNED_ATTRS:
            issue = "calls ." + func.attr
        else:
            issue = ""
        if issue and issue not in seen:
            seen.add(issue)
            found.append(issue)
    return found


def address_problems(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in BANNED_ADDR or "0.0.0.0" in node.value or "localhost" in node.value:
                if node.value not in found:
                    found.append(node.value)
    return found


def header_problems(text):
    found = []
    if "Authorization" in text:
        found.append("Authorization")
    if "Cookie" in text:
        found.append("Cookie")
    return found


def g1_shape():
    missing = miss_detail(PRODUCT_RELS)
    if missing:
        return FAIL, missing
    path = REPO_ROOT / SERVE_REL
    try:
        source = read_text(path)
        tree = ast.parse(source)
    except SyntaxError as exc:
        return FAIL, "serve_local.py does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return FAIL, "serve_local.py unreadable: " + type(exc).__name__
    problems = []
    bindings = module_bindings(tree)
    funcs = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    asyncs = {node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
    for name in NEED_DATA:
        if name not in bindings and name not in funcs:
            problems.append("missing " + name)
    host_node = bindings.get("HOST")
    if not isinstance(host_node, ast.Constant) or host_node.value != "127.0.0.1":
        problems.append('HOST is not the literal "127.0.0.1"')
    for name in NEED_FUNCS:
        if name in asyncs and name not in funcs:
            problems.append("async " + name)
        elif name not in funcs and name not in bindings:
            problems.append("missing " + name)
    if not imports_decide(tree):
        problems.append("missing from stop_policy import decide")
    if defines_decide(tree):
        problems.append("defines decide")
    problems.extend(import_problems(tree))
    problems.extend(call_problems(tree))
    for value in address_problems(tree):
        problems.append("address literal " + value)
    for value in header_problems(source):
        problems.append("header name " + value)
    if problems:
        return FAIL, cap_text(problems)
    data, status, detail = call_driver(REPO_ROOT, {"mode": "import_probe"}, 10)
    if data is None and status == BLOCKED:
        return BLOCKED, detail
    if data is None and detail.startswith("driver did not return"):
        return FAIL, "import serve_local did not return"
    if data is None:
        return FAIL, detail
    if data.get("import_error"):
        problems.append("import " + str(data.get("import_error")))
    if data.get("stdout"):
        problems.append("import stdout not empty")
    if data.get("stderr"):
        problems.append("import stderr not empty")
    if data.get("binds"):
        problems.append("import bound a port")
    if data.get("host") != "127.0.0.1":
        problems.append("runtime HOST")
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "import_silent=True binds=0"


def g2_states():
    if miss_detail((SERVE_REL,)):
        return FAIL, "missing " + SERVE_REL
    codes = list(STATE_CODES) + ["IDLE", "", None, "running"]
    data, status, detail = call_driver(
        REPO_ROOT, {"mode": "inspect", "codes": codes}, 30)
    if status:
        return status, detail
    problems = []
    if data.get("labels") != STATE_LABELS:
        problems.append("STATE_LABELS")
    if data.get("busy_type") != "frozenset" or set(data.get("busy") or []) != set(BUSY_STATES):
        problems.append("BUSY_STATES")
    views = data.get("views")
    if not isinstance(views, list) or len(views) != len(codes):
        problems.append("state_view count")
    else:
        for code, got in zip(codes, views):
            expect = expected_view(code)
            if not isinstance(got, dict) or set(got) != {"code", "label", "busy", "terminal"}:
                problems.append("state_view keys " + ascii_text(code))
                continue
            if not same(got, expect) or type(got.get("busy")) is not bool or type(got.get("terminal")) is not bool:
                problems.append("state_view " + ascii_text(code))
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "codes=15 unknown=4"


def g3_one_job(job, base, ids):
    problems = []
    label = job_id_of(job)
    if set(job) != JOB_KEYS:
        return [label + " keys"]
    for key in ("snapshot", "contract", "policy"):
        problems.extend(shape_problems(job.get(key), base.get(key), label + "." + key))
    now = job.get("now")
    if isinstance(base.get("now"), dict):
        problems.extend(shape_problems(now, base.get("now"), label + ".now"))
    elif isinstance(now, (dict, list)) or not is_number(now):
        problems.append(label + ".now")
    snap = job.get("snapshot") if isinstance(job.get("snapshot"), dict) else {}
    con = job.get("contract") if isinstance(job.get("contract"), dict) else {}
    disp = job.get("display") if isinstance(job.get("display"), dict) else {}
    if snap.get("host") != "online":
        problems.append(label + " snapshot.host")
    jid = con.get("job_id")
    match = JOB_ID_RE.match(jid) if isinstance(jid, str) else None
    if match is None:
        problems.append(label + " job_id")
    else:
        if match.group(1) != con.get("job_type"):
            problems.append(label + " job_type")
        if jid in ids:
            problems.append(label + " duplicate job_id")
        ids.add(jid)
    if type(con.get("cu_cap")) is not int or con.get("cu_cap") != 10:
        problems.append(label + " cu_cap")
    if con.get("submitted_by") not in ("human", "bot:demo"):
        problems.append(label + " submitted_by")
    if set(disp) != DISPLAY_KEYS:
        problems.append(label + " display keys")
        return problems
    title = disp.get("title")
    if not isinstance(title, str) or title == "" or not has_cjk(title):
        problems.append(label + " title")
    if type(disp.get("progress_total")) is not int or disp.get("progress_total") <= 0:
        problems.append(label + " progress_total")
    if type(disp.get("cu_balance")) is not int or disp.get("cu_balance") != 100:
        problems.append(label + " cu_balance")
    rate = disp.get("cu_rate_per_hour")
    if not is_number(rate) or rate < 0 or rate > 10:
        problems.append(label + " cu_rate")
    note = disp.get("note")
    if not isinstance(note, str):
        problems.append(label + " note")
    elif snap.get("state") == "BLOCKED" and note == "":
        problems.append(label + " blocked note")
    files = disp.get("files")
    if not isinstance(files, list):
        problems.append(label + " files")
    else:
        for index, item in enumerate(files):
            prefix = label + " file " + str(index)
            if not isinstance(item, dict) or set(item) != FILE_KEYS:
                problems.append(prefix + " keys")
                continue
            if not isinstance(item.get("name"), str) or not FILE_NAME_RE.match(item.get("name")):
                problems.append(prefix + " name")
            if type(item.get("size_bytes")) is not int or item.get("size_bytes") < 0:
                problems.append(prefix + " size")
            if not isinstance(item.get("sha256_8"), str) or not SHA8_RE.match(item.get("sha256_8")):
                problems.append(prefix + " sha")
            if item.get("verify") not in ("verified", "unverified", "mismatch"):
                problems.append(prefix + " verify")
            if type(item.get("landed")) is not bool:
                problems.append(prefix + " landed")
    timeline = disp.get("timeline")
    if not isinstance(timeline, list):
        problems.append(label + " timeline")
    else:
        for index, item in enumerate(timeline):
            prefix = label + " timeline " + str(index)
            if not isinstance(item, dict) or set(item) != TIMELINE_KEYS:
                problems.append(prefix + " keys")
                continue
            if not is_number(item.get("at")):
                problems.append(prefix + " at")
            origin = item.get("from")
            if origin is not None and origin not in STATE_LABELS:
                problems.append(prefix + " from")
            if item.get("to") not in STATE_LABELS:
                problems.append(prefix + " to")
            if item.get("by") not in ("H", "B", "S"):
                problems.append(prefix + " by")
    return problems


def g3_fixture():
    need = miss_detail((JOBS_REL, SCENARIO_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    base_doc, err = load_json(SCENARIO_REL)
    if err:
        return FAIL, err
    if not isinstance(doc, dict) or set(doc) != TOP_KEYS:
        return FAIL, "top-level keys"
    problems = []
    if type(doc.get("schema")) is not int or doc.get("schema") != 1:
        problems.append("schema")
    if doc.get("notice") != NOTICE:
        problems.append("notice")
    if doc.get("host") != "online":
        problems.append("host")
    jobs = doc.get("jobs")
    base = base_doc.get("base") if isinstance(base_doc, dict) else None
    if not isinstance(base, dict):
        return FAIL, "scenarios base"
    if not isinstance(jobs, list):
        return FAIL, "jobs is not a list"
    if len(jobs) < 15:
        problems.append("job count " + str(len(jobs)))
    ids = set()
    states = set()
    types = set()
    covered = {1: False, 2: False, 3: False, 4: False, 5: False, 6: False}
    runnable = []
    for job in jobs:
        if not isinstance(job, dict):
            problems.append("job is not an object")
            continue
        problems.extend(g3_one_job(job, base, ids))
        snap = job.get("snapshot") if isinstance(job.get("snapshot"), dict) else {}
        con = job.get("contract") if isinstance(job.get("contract"), dict) else {}
        disp = job.get("display") if isinstance(job.get("display"), dict) else {}
        if snap.get("state") in STATE_LABELS:
            states.add(snap.get("state"))
        if con.get("job_type") in ("J1", "J3", "WAN"):
            types.add(con.get("job_type"))
        probe = snap.get("probe") if isinstance(snap.get("probe"), dict) else {}
        if (snap.get("state") == "RUNNING" and snap.get("human_hold") is False
                and snap.get("human_command") == "none" and snap.get("bot_request") == "none"
                and probe.get("status") == "ok"):
            covered[3] = True
        if snap.get("human_hold") is True and con.get("submitted_by") == "bot:demo":
            covered[4] = True
        if snap.get("state") == "RELEASE_UNCONFIRMED" and snap.get("release_check") in ("active_nonzero", "check_failed"):
            covered[5] = True
        files = disp.get("files") if isinstance(disp.get("files"), list) else []
        if any(isinstance(item, dict) and item.get("verify") == "mismatch" for item in files):
            covered[6] = True
        if isinstance(job.get("snapshot"), dict) and isinstance(job.get("contract"), dict):
            runnable.append(job)
    if states != set(STATE_CODES):
        problems.append("states " + ",".join(sorted(set(STATE_CODES) - states)))
    if types != {"J1", "J3", "WAN"}:
        problems.append("job types")
    for number in (3, 4, 5, 6):
        if not covered[number]:
            problems.append("coverage " + str(number))
    decided, status, detail = decide_items(REPO_ROOT, [job_item(job) for job in runnable])
    if status and not problems:
        return status, detail
    if status:
        problems.append(detail)
    elif decided is not None:
        for job, item in zip(runnable, decided):
            if not item.get("ok") or not isinstance(item.get("result"), dict):
                problems.append(job_id_of(job) + " decide " + str(item.get("error") or "shape"))
    hits = hygiene_hits(JOBS_REL)
    problems.extend(hits)
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "jobs=" + str(len(jobs))


def wind_items(jobs, host):
    items = []
    for job in jobs:
        trial = copy.deepcopy(job)
        trial["snapshot"]["host"] = host
        items.append(trial)
    return items


def expected_wind(jobs, decided):
    found = []
    for job, item in zip(jobs, decided):
        if not item.get("ok") or not isinstance(item.get("result"), dict):
            continue
        result = item["result"]
        shutdown = result.get("action") == "REQUEST_SAVE" and result.get("reason_code") == "HOST_SHUTDOWN"
        offline = result.get("reason_code") == "HOST_OFFLINE_REMOTE_RUNNING"
        if shutdown or offline:
            found.append(job["contract"]["job_id"])
    return found


def g4_api():
    need = miss_detail((SERVE_REL, JOBS_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, list) or not jobs:
        return FAIL, "jobs.json has no jobs"
    notice = doc.get("notice")
    decisions, status, detail = decide_items(REPO_ROOT, [job_item(job) for job in jobs])
    if status:
        return status, detail
    wind_jobs = wind_items(jobs, "shutting_down") + wind_items(jobs, "just_booted")
    wind_decided, status, detail = decide_items(REPO_ROOT, [job_item(job) for job in wind_jobs])
    if status:
        return status, detail
    shut_expect = [] if False else expected_wind(wind_jobs[:len(jobs)], wind_decided[:len(jobs)])
    boot_expect = expected_wind(wind_jobs[len(jobs):], wind_decided[len(jobs):])
    summaries = [expected_summary(notice, job, item) for job, item in zip(jobs, decisions)]
    list_calls = [{"method": "GET", "path": "/api/jobs", "body": None}]
    for job in jobs:
        list_calls.append({
            "method": "GET",
            "path": "/api/jobs/" + job_id_of(job),
            "body": None,
        })
    sessions = [
        {"calls": [{"method": method, "path": path, "body": None} for method, path in [
            ("GET", item[0]) for item in STATIC_CASES
        ]]},
        {"calls": list_calls},
        {"calls": [{"method": "GET", "path": path, "body": None} for path in NOT_FOUND_PATHS]},
        {"calls": [
            {"method": "PUT", "path": "/api/jobs", "body": None},
            {"method": "DELETE", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/reset", "body": None},
            {"method": "POST", "path": "/api/reset", "body": []},
            {"method": "POST", "path": "/api/jobs/" + job_id_of(jobs[0]) + "/command", "body": {"command": "nope"}},
        ]},
        {"calls": [
            {"method": "POST", "path": "/api/host", "body": {"host": "shutting_down"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
        {"calls": [
            {"method": "POST", "path": "/api/host", "body": {"host": "just_booted"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
    ]
    # Static session built above lost the filename pairing. Rebuild it plainly.
    sessions[0] = {"calls": [
        {"method": "GET", "path": path, "body": None} for path, _name in STATIC_CASES
    ]}
    got_sessions, status, detail = run_sessions(REPO_ROOT, sessions, 60)
    if status:
        return status, detail
    problems = []
    static_session = got_sessions[0]
    for index, (_path, name) in enumerate(STATIC_CASES):
        got, err = call_of(static_session, index)
        if err:
            problems.append("static " + name + " " + err)
            continue
        if got.get("status") != 200 or not same(got.get("payload"), {"static": name}):
            problems.append("static " + name)
    overview, err = call_of(got_sessions[1], 0)
    if err:
        problems.append("list " + err)
    else:
        payload = overview.get("payload")
        if overview.get("status") != 200 or not isinstance(payload, dict):
            problems.append("list status")
        elif set(payload) != {"notice", "host", "host_label", "wind_down", "jobs"}:
            problems.append("list keys")
        else:
            if payload.get("notice") != notice:
                problems.append("notice")
            if payload.get("host") != "online" or payload.get("host_label") != HOST_LABELS["online"]:
                problems.append("host_label")
            if payload.get("wind_down") != []:
                problems.append("online wind_down")
            rows = payload.get("jobs")
            if not isinstance(rows, list) or len(rows) != len(summaries):
                problems.append("jobs length")
            else:
                for job, expect, row in zip(jobs, summaries, rows):
                    if not same(row, expect):
                        problems.append(job_id_of(job) + " " + ",".join(diff_keys(row, expect)[:4]))
                    if isinstance(row, dict) and job["snapshot"].get("state") == "RELEASE_UNCONFIRMED":
                        for field in ("state_label", "release_label"):
                            text = row.get(field) if isinstance(row.get(field), str) else ""
                            if any(word in text for word in ("完成", "已睡", "睡眠")):
                                problems.append(job_id_of(job) + " " + field + " banned")
                            if text != "釋放未確認":
                                problems.append(job_id_of(job) + " " + field)
                        if row.get("busy") is not True or row.get("terminal") is not False:
                            problems.append(job_id_of(job) + " busy")
                        if row.get("release_label") == "已確認 0 active":
                            problems.append(job_id_of(job) + " confirmed")
        for index, job in enumerate(jobs):
            got, err = call_of(got_sessions[1], index + 1)
            jid = job_id_of(job)
            if err:
                problems.append(jid + " detail " + err)
                continue
            payload = got.get("payload")
            expect = summaries[index]
            if got.get("status") != 200 or not isinstance(payload, dict):
                problems.append(jid + " detail status")
                continue
            if set(payload) != set(SUMMARY_KEYS) | {"checkpoint", "files", "timeline", "contract_summary", "audit"}:
                problems.append(jid + " detail keys")
                continue
            for key in SUMMARY_KEYS:
                if not same(payload.get(key), expect.get(key)):
                    problems.append(jid + " detail " + key)
                    break
            if not same(payload.get("checkpoint"), job["snapshot"].get("checkpoint")):
                problems.append(jid + " checkpoint")
            if not same(payload.get("files"), job["display"].get("files")):
                problems.append(jid + " files")
            if not same(payload.get("timeline"), job["display"].get("timeline")):
                problems.append(jid + " timeline")
            if not isinstance(payload.get("contract_summary"), dict):
                problems.append(jid + " contract_summary")
            if payload.get("audit") != []:
                problems.append(jid + " audit")
    for index, path in enumerate(NOT_FOUND_PATHS):
        got, err = call_of(got_sessions[2], index)
        if err:
            problems.append("404 " + path + " " + err)
            continue
        payload = got.get("payload")
        shape = error_shape(payload)
        if got.get("status") != 404 or shape or payload.get("reason_code") != "NOT_FOUND":
            problems.append("404 " + path)
    error_cases = (
        (0, 405, "METHOD_NOT_ALLOWED"),
        (1, 405, "METHOD_NOT_ALLOWED"),
        (2, 400, "BAD_JSON"),
        (3, 400, "BAD_JSON"),
        (4, 400, "BAD_PARAM"),
    )
    for index, status_code, reason in error_cases:
        got, err = call_of(got_sessions[3], index)
        if err:
            problems.append(reason + " " + err)
            continue
        payload = got.get("payload")
        shape = error_shape(payload)
        if got.get("status") != status_code or shape or payload.get("reason_code") != reason:
            problems.append(reason + " status " + str(got.get("status")))
    for index, expect_wind, label in (
        (4, shut_expect, "shutting_down"),
        (5, boot_expect, "just_booted"),
    ):
        posted, err = call_of(got_sessions[index], 0)
        listed, err2 = call_of(got_sessions[index], 1)
        if err or err2:
            problems.append(label + " " + (err or err2))
            continue
        payload = listed.get("payload") if isinstance(listed.get("payload"), dict) else {}
        if posted.get("status") != 200 or listed.get("status") != 200:
            problems.append(label + " status")
        elif payload.get("host") != label or payload.get("wind_down") != expect_wind:
            problems.append(label + " wind_down")
        elif label != "online" and payload.get("host_label") != HOST_LABELS[label]:
            problems.append(label + " host_label")
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "jobs=" + str(len(jobs))


def g5_apply():
    need = miss_detail((SERVE_REL, JOBS_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, list) or not jobs:
        return FAIL, "jobs.json has no jobs"
    notice = doc.get("notice")
    trials = []
    items = []
    plan = []
    for job in jobs:
        jid = job_id_of(job)
        for action in ("tick",) + COMMANDS:
            trial = copy.deepcopy(job)
            if action != "tick":
                trial["snapshot"]["human_command"] = action
            trials.append(trial)
            items.append(job_item(trial))
            plan.append((job, action, jid))
    decided, status, detail = decide_items(REPO_ROOT, items)
    if status:
        return status, detail
    posts = []
    post_items = []
    raised = []
    for (job, _action, _jid), item in zip(plan, decided):
        post, failed = apply_expected(job, item)
        posts.append(post)
        post_items.append(job_item(post))
        raised.append(failed or not item.get("ok"))
    post_decided, status, detail = decide_items(REPO_ROOT, post_items)
    if status:
        return status, detail
    sessions = []
    for (job, action, jid), _item in zip(plan, decided):
        if action == "tick":
            body = {}
            path = "/api/jobs/" + jid + "/tick"
        else:
            body = {"command": action}
            if action == "stop_now":
                body["confirm"] = True
            path = "/api/jobs/" + jid + "/command"
        sessions.append({"calls": [{"method": "POST", "path": path, "body": body}]})
    got_sessions, status, detail = run_sessions(REPO_ROOT, sessions, 90)
    if status:
        return status, detail
    problems = []
    for index, ((job, action, jid), trial_dec, post, post_dec, did_raise) in enumerate(
            zip(plan, decided, posts, post_decided, raised)):
        got, err = call_of(got_sessions[index], 0)
        if err:
            problems.append(jid + " " + action + " " + err)
            continue
        payload = got.get("payload")
        if did_raise:
            shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
            if got.get("status") != 422 or shape or payload.get("reason_code") != "INPUT_INVALID":
                problems.append(jid + " " + action + " expected 422")
            continue
        expect_job = expected_summary(notice, post, post_dec)
        if got.get("status") != 200 or not isinstance(payload, dict) or set(payload) != APPLY_KEYS:
            problems.append(jid + " " + action + " response keys")
            continue
        result = trial_dec.get("result") if isinstance(trial_dec.get("result"), dict) else {}
        accepted = result.get("action") != "REJECT_REQUEST"
        if payload.get("job_id") != jid or payload.get("accepted") is not accepted:
            problems.append(jid + " " + action + " accepted")
        if not same(payload.get("decision"), result) or set(payload.get("decision") or {}) != set(DECISION_KEYS):
            problems.append(jid + " " + action + " decision")
        if not same(payload.get("job"), expect_job):
            problems.append(jid + " " + action + " job " + ",".join(diff_keys(payload.get("job"), expect_job)[:3]))
        if result.get("action") == "REJECT_REQUEST" and payload.get("job", {}).get("state") != job["snapshot"].get("state"):
            problems.append(jid + " " + action + " reject changed state")
        if len(problems) >= 8:
            break
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "cases=" + str(len(plan))


def bot_pause_body(jid):
    return {"action": "request_pause", "caller": "bot:demo", "job_id": jid}


def g6_hold():
    need = miss_detail((SERVE_REL, JOBS_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, list):
        return FAIL, "jobs.json has no jobs"
    running = coverage_job(jobs, 3)
    held = coverage_job(jobs, 4)
    if running is None or held is None:
        return FAIL, "coverage job missing"
    run_id = job_id_of(running)
    held_id = job_id_of(held)
    sessions = [
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/bot", "body": bot_pause_body(run_id)},
            {"method": "POST", "path": "/api/reset", "body": {}},
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + run_id + "/command", "body": {"command": "stop_after_save"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/bot", "body": bot_pause_body(run_id)},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + run_id + "/command", "body": {"command": "stop_now"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + run_id + "/command", "body": {"command": "stop_now", "confirm": "yes"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + run_id + "/command", "body": {"command": "stop_now", "confirm": 1}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
        {"calls": [
            {"method": "POST", "path": "/api/jobs/" + run_id + "/command", "body": {"command": "stop_now", "confirm": True}},
        ]},
        {"calls": [
            {"method": "POST", "path": "/api/bot", "body": bot_pause_body(held_id)},
        ]},
    ]
    got, status, detail = run_sessions(REPO_ROOT, sessions, 60)
    if status:
        return status, detail
    problems = []
    hold, err = call_of(got[0], 1)
    if err:
        problems.append("bot pause " + err)
    else:
        payload = hold.get("payload")
        if (hold.get("status") != 200 or not isinstance(payload, dict)
                or set(payload) != BOT_KEYS["request_pause"]
                or payload.get("ok") is not True or payload.get("accepted") is not True
                or payload.get("reason_code") != "BOT_PAUSE" or payload.get("job_id") != run_id):
            problems.append("bot pause")
    before, err_b = call_of(got[0], 0)
    after_reset, err_r = call_of(got[0], 3)
    if err_b or err_r or not same(before.get("payload"), after_reset.get("payload")):
        problems.append("reset")
    saved, err = call_of(got[0], 4)
    if err:
        problems.append("stop_after_save " + err)
    else:
        job = saved.get("payload").get("job") if isinstance(saved.get("payload"), dict) else None
        if saved.get("status") != 200 or not isinstance(job, dict) or job.get("human_hold") is not True:
            problems.append("human_hold")
    mid, err_m = call_of(got[0], 5)
    end, err_e = call_of(got[0], 7)
    rejected, err = call_of(got[0], 6)
    if err or err_m or err_e:
        problems.append("held pause")
    else:
        payload = rejected.get("payload")
        if (rejected.get("status") != 200 or not isinstance(payload, dict)
                or payload.get("accepted") is not False or payload.get("reason_code") != "HUMAN_HOLD"):
            problems.append("HUMAN_HOLD")
        if not same(mid.get("payload"), end.get("payload")):
            problems.append("HUMAN_HOLD changed state")
    for index, label in ((1, "confirm absent"), (2, "confirm yes"), (3, "confirm 1")):
        earlier, err_a = call_of(got[index], 0)
        denied, err_d = call_of(got[index], 1)
        later, err_c = call_of(got[index], 2)
        if err_a or err_d or err_c:
            problems.append(label)
            continue
        payload = denied.get("payload")
        shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
        if (denied.get("status") != 409 or shape or payload.get("reason_code") != "CONFIRM_REQUIRED"
                or not same(earlier.get("payload"), later.get("payload"))):
            problems.append(label)
    confirmed, err = call_of(got[4], 0)
    if err:
        problems.append("confirm true " + err)
    else:
        payload = confirmed.get("payload") if isinstance(confirmed.get("payload"), dict) else {}
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
        if (confirmed.get("status") != 200 or decision.get("action") != "RELEASE"
                or decision.get("next_state") != "RELEASING" or job.get("state") != "RELEASING"):
            problems.append("RELEASE/RELEASING")
    owned, err = call_of(got[5], 0)
    if err:
        problems.append("coverage 4 " + err)
    else:
        payload = owned.get("payload") if isinstance(owned.get("payload"), dict) else {}
        if owned.get("status") != 200 or payload.get("reason_code") != "HUMAN_HOLD" or payload.get("accepted") is not False:
            problems.append("coverage 4 HUMAN_HOLD")
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "running=" + run_id + " held=" + held_id


def g7_bot():
    need = miss_detail((SERVE_REL, JOBS_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, list) or not jobs:
        return FAIL, "jobs.json has no jobs"
    decisions, status, detail = decide_items(REPO_ROOT, [job_item(job) for job in jobs])
    if status:
        return status, detail
    by_id = {}
    reasons = {}
    messages = {}
    for job, item in zip(jobs, decisions):
        jid = job_id_of(job)
        by_id[jid] = job
        result = item.get("result") if item.get("ok") else None
        reasons[jid] = result.get("reason_code") if isinstance(result, dict) else "INPUT_INVALID"
        messages[jid] = result.get("ui_message") if isinstance(result, dict) else ""
    running = coverage_job(jobs, 3)
    if running is None:
        return FAIL, "coverage job missing"
    run_id = job_id_of(running)
    sessions = []
    sessions.append({"calls": [
        {"method": "POST", "path": "/api/bot", "body": {"action": "list_jobs", "caller": "bot:demo"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "list_jobs", "caller": "bot:demo", "state": "RUNNING"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "list_jobs", "caller": "bot:demo", "state": "IDLE"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "get_status", "caller": "bot:demo", "job_id": run_id}},
        {"method": "POST", "path": "/api/bot", "body": bot_pause_body(run_id)},
        {"method": "GET", "path": "/api/jobs", "body": None},
        {"method": "POST", "path": "/api/bot", "body": {"action": "submit_job", "caller": "bot:demo"}},
        {"method": "GET", "path": "/api/jobs", "body": None},
    ]})
    for action in DISALLOWED_ACTIONS:
        sessions.append({"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/bot", "body": {"action": action, "caller": "bot:demo"}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]})
    for body in (
        {"action": "list_jobs"},
        {"action": "list_jobs", "caller": "human"},
    ):
        sessions.append({"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/bot", "body": body},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]})
    for key in ("Token", "api_key", "X-Auth"):
        body = {"action": "list_jobs", "caller": "bot:demo", key: SENTINEL}
        sessions.append({"calls": [
            {"method": "POST", "path": "/api/bot", "body": body},
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "GET", "path": "/api/jobs/" + run_id, "body": None},
        ]})
    got, status, detail = run_sessions(REPO_ROOT, sessions, 60)
    if status:
        return status, detail
    problems = []

    def rows_by_id(rows):
        found = {}
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("job_id"), str):
                return None
            if row["job_id"] in found:
                return None
            found[row["job_id"]] = row
        return found

    listed, err = call_of(got[0], 0)
    if err:
        problems.append("list_jobs " + err)
    else:
        payload = listed.get("payload")
        if listed.get("status") != 200 or not isinstance(payload, dict) or set(payload) != BOT_KEYS["list_jobs"]:
            problems.append("list_jobs keys")
        elif payload.get("ok") is not True or has_key(payload, FORBIDDEN_BODY_KEYS):
            problems.append("list_jobs body")
        else:
            found = rows_by_id(payload.get("jobs"))
            if found is None or set(found) != set(by_id):
                problems.append("list_jobs rows")
            else:
                for jid, row in found.items():
                    job = by_id[jid]
                    progress = {
                        "value": job["snapshot"]["progress"]["value"],
                        "total": job["display"]["progress_total"],
                    }
                    if (set(row) != LIST_ROW_KEYS or row.get("state") != job["snapshot"].get("state")
                            or row.get("state_label") != STATE_LABELS.get(row.get("state"))
                            or not same(row.get("progress"), progress)
                            or row.get("reason_code") != reasons.get(jid)):
                        problems.append("list row " + jid)
                        break
    filtered, err = call_of(got[0], 1)
    if err:
        problems.append("filter " + err)
    else:
        payload = filtered.get("payload") if isinstance(filtered.get("payload"), dict) else {}
        found = rows_by_id(payload.get("jobs"))
        want = {job_id_of(job) for job in jobs if job["snapshot"].get("state") == "RUNNING"}
        if filtered.get("status") != 200 or found is None or set(found) != want:
            problems.append("state filter")
        elif any(row.get("state") != "RUNNING" for row in found.values()):
            problems.append("state filter value")
    bad_filter, err = call_of(got[0], 2)
    if err:
        problems.append("bad filter " + err)
    else:
        payload = bad_filter.get("payload")
        shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
        if bad_filter.get("status") != 400 or shape or payload.get("reason_code") != "BAD_PARAM":
            problems.append("bad filter")
    status_call, err = call_of(got[0], 3)
    if err:
        problems.append("get_status " + err)
    else:
        payload = status_call.get("payload")
        job = by_id[run_id]
        progress = {
            "value": job["snapshot"]["progress"]["value"],
            "total": job["display"]["progress_total"],
        }
        if (status_call.get("status") != 200 or not isinstance(payload, dict)
                or set(payload) != BOT_KEYS["get_status"] or payload.get("ok") is not True
                or payload.get("job_id") != run_id or payload.get("state") != "RUNNING"
                or payload.get("state_label") != STATE_LABELS["RUNNING"]
                or not same(payload.get("progress"), progress)
                or payload.get("reason_code") != reasons.get(run_id)
                or payload.get("ui_message") != messages.get(run_id)
                or has_key(payload, FORBIDDEN_BODY_KEYS)):
            problems.append("get_status")
    paused, err = call_of(got[0], 4)
    if err:
        problems.append("request_pause " + err)
    else:
        payload = paused.get("payload")
        if (paused.get("status") != 200 or not isinstance(payload, dict)
                or set(payload) != BOT_KEYS["request_pause"] or has_key(payload, FORBIDDEN_BODY_KEYS)):
            problems.append("request_pause keys")
    before_submit, err_b = call_of(got[0], 5)
    submitted, err = call_of(got[0], 6)
    after_submit, err_a = call_of(got[0], 7)
    if err or err_b or err_a:
        problems.append("submit_job")
    else:
        payload = submitted.get("payload")
        if (submitted.get("status") != 200 or not isinstance(payload, dict)
                or set(payload) != BOT_KEYS["submit_job"] or payload.get("ok") is not True
                or payload.get("accepted") is not False or payload.get("reason_code") != "NOT_IN_PROTOTYPE"
                or has_key(payload, FORBIDDEN_BODY_KEYS)
                or not same(before_submit.get("payload"), after_submit.get("payload"))):
            problems.append("submit_job")
    for index, action in enumerate(DISALLOWED_ACTIONS):
        before, err_b = call_of(got[index + 1], 0)
        denied, err_d = call_of(got[index + 1], 1)
        after, err_a = call_of(got[index + 1], 2)
        label = "disallowed empty" if action == "" else "disallowed " + action
        if err_b or err_d or err_a:
            problems.append(label)
            continue
        payload = denied.get("payload")
        shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
        if (denied.get("status") != 403 or shape or payload.get("reason_code") != "ACTION_NOT_ALLOWED"
                or has_key(payload, FORBIDDEN_BODY_KEYS)
                or not same(before.get("payload"), after.get("payload"))):
            problems.append(label)
    caller_base = 1 + len(DISALLOWED_ACTIONS)
    for offset, label in ((0, "missing caller"), (1, "human caller")):
        before, err_b = call_of(got[caller_base + offset], 0)
        denied, err_d = call_of(got[caller_base + offset], 1)
        after, err_a = call_of(got[caller_base + offset], 2)
        if err_b or err_d or err_a:
            problems.append(label)
            continue
        payload = denied.get("payload")
        shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
        if (denied.get("status") != 400 or shape or payload.get("reason_code") != "BAD_CALLER"
                or not same(before.get("payload"), after.get("payload"))):
            problems.append(label)
    cred_base = caller_base + 2
    for offset, key in enumerate(("Token", "api_key", "X-Auth")):
        denied, err_d = call_of(got[cred_base + offset], 0)
        listed, err_l = call_of(got[cred_base + offset], 1)
        detail_call, err_i = call_of(got[cred_base + offset], 2)
        if err_d or err_l or err_i:
            problems.append("credential " + key)
            continue
        payload = denied.get("payload")
        shape = error_shape(payload) if isinstance(payload, dict) else ["payload"]
        leaked = (
            contains_text(payload, SENTINEL)
            or contains_text(denied.get("audits"), SENTINEL)
            or contains_text(listed.get("payload"), SENTINEL)
            or contains_text(detail_call.get("payload"), SENTINEL)
            or contains_text(listed.get("audits"), SENTINEL)
        )
        if (denied.get("status") != 400 or shape or payload.get("reason_code") != "CREDENTIAL_REFUSED" or leaked):
            problems.append("credential " + key)
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "actions=4"


def audit_record_problems(record, expect):
    problems = []
    if not isinstance(record, dict) or set(record) != set(AUDIT_KEYS):
        return ["audit keys"]
    for key, value in expect.items():
        if record.get(key) != value:
            problems.append("audit " + key)
    return problems


def g8_audit():
    need = miss_detail((SERVE_REL, JOBS_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    running = coverage_job(jobs, 3) if isinstance(jobs, list) else None
    if running is None:
        return FAIL, "coverage job missing"
    jid = job_id_of(running)
    moment = running.get("now")
    sessions = [{"calls": [
        {"method": "GET", "path": "/api/jobs", "body": None},
        {"method": "POST", "path": "/api/jobs/" + jid + "/tick", "body": {}},
        {"method": "POST", "path": "/api/jobs/" + jid + "/command", "body": {"command": "nope"}},
        {"method": "POST", "path": "/api/jobs/" + jid + "/command", "body": {"command": "stop_now"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "exec", "caller": "bot:demo"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "list_jobs"}},
        {"method": "POST", "path": "/api/bot", "body": {"action": "list_jobs", "caller": "bot:demo", "Token": SENTINEL}},
        {"method": "GET", "path": "/api/jobs/" + jid, "body": None},
        {"method": "POST", "path": "/api/reset", "body": {}},
        {"method": "GET", "path": "/api/jobs/" + jid, "body": None},
    ]},
        {"calls": [
            {"method": "POST", "path": "/api/reset", "body": None},
        ]},
        {"calls": [
            {"method": "POST", "path": "/api/nope", "body": {}},
        ]},
    ]
    got, status, detail = run_sessions(REPO_ROOT, sessions, 60)
    if status:
        return status, detail
    session = got[0]
    problems = []
    calls = []
    for index in range(10):
        item, err = call_of(session, index)
        if err:
            return FAIL, "call " + str(index) + " " + err
        calls.append(item)
    if calls[0].get("audits") != []:
        problems.append("fresh audit")
    tick_payload = calls[1].get("payload") if isinstance(calls[1].get("payload"), dict) else {}
    tick_decision = tick_payload.get("decision") if isinstance(tick_payload.get("decision"), dict) else {}
    expected = [
        (1, {"at": moment, "caller": "human", "job_id": jid, "result": tick_decision.get("reason_code")}),
        (2, {"at": moment, "caller": "human", "job_id": jid, "result": "BAD_PARAM"}),
        (3, {"at": moment, "caller": "human", "job_id": jid, "result": "CONFIRM_REQUIRED"}),
        (4, {"at": None, "caller": "bot:demo", "job_id": None, "result": "ACTION_NOT_ALLOWED"}),
        (5, {"result": "BAD_CALLER", "job_id": None, "at": None}),
        (6, {"result": "CREDENTIAL_REFUSED"}),
    ]
    previous = 0
    for index, fields in expected:
        audits = calls[index].get("audits")
        if not isinstance(audits, list) or len(audits) != previous + 1:
            problems.append("audit count at " + str(index))
            break
        problems.extend(audit_record_problems(audits[-1], fields))
        previous += 1
    if contains_text(calls[6].get("audits"), SENTINEL) or contains_text(calls[6].get("payload"), SENTINEL):
        problems.append("sentinel in audit")
    detail_payload = calls[7].get("payload") if isinstance(calls[7].get("payload"), dict) else {}
    visible = detail_payload.get("audit")
    wanted = [item for item in calls[6].get("audits") or [] if item.get("job_id") == jid]
    if calls[7].get("audits") != calls[6].get("audits"):
        problems.append("GET added audit")
    if visible != wanted:
        problems.append("detail audit")
    elif any(item.get("job_id") != jid for item in visible if isinstance(item, dict)):
        problems.append("detail job_id")
    reset_audits = calls[8].get("audits")
    if (not isinstance(reset_audits, list) or len(reset_audits) != 1
            or audit_record_problems(reset_audits[0], {
                "at": None, "caller": "human", "job_id": None, "result": "RESET",
            })):
        problems.append("reset audit")
    cleared = calls[9].get("payload") if isinstance(calls[9].get("payload"), dict) else {}
    if cleared.get("audit") != []:
        problems.append("detail after reset")
    bad_json, err = call_of(got[1], 0)
    if err:
        problems.append("bad json " + err)
    else:
        audits = bad_json.get("audits")
        payload = bad_json.get("payload") if isinstance(bad_json.get("payload"), dict) else {}
        if (bad_json.get("status") != 400 or payload.get("reason_code") != "BAD_JSON"
                or not isinstance(audits, list) or len(audits) != 1
                or audit_record_problems(audits[0], {"result": "BAD_JSON", "job_id": None, "at": None})):
            problems.append("bad json audit")
    unknown, err = call_of(got[2], 0)
    if err:
        problems.append("unknown post " + err)
    else:
        audits = unknown.get("audits")
        payload = unknown.get("payload") if isinstance(unknown.get("payload"), dict) else {}
        if (unknown.get("status") != 404 or payload.get("reason_code") != "NOT_FOUND"
                or not isinstance(audits, list) or len(audits) != 1
                or audit_record_problems(audits[0], {"result": "NOT_FOUND"})):
            problems.append("unknown post audit")
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "posts=8 reset=1"


def snapshot_bits(payload):
    rows = []
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return None
    for row in payload["jobs"]:
        if not isinstance(row, dict):
            return None
        rows.append((row.get("job_id"), row.get("state"), row.get("human_hold")))
    return rows


def g9_probe(root, jid):
    sessions = [
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + jid + "/tick", "body": {}},
        ]},
        {"calls": [
            {"method": "GET", "path": "/api/jobs", "body": None},
            {"method": "POST", "path": "/api/jobs/" + jid + "/tick", "body": {}},
            {"method": "GET", "path": "/api/jobs", "body": None},
        ]},
    ]
    got, status, detail = run_sessions(root, sessions, 60)
    if status:
        return None, detail
    return got, ""


def reason_codes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return None
    found = []
    for row in payload["jobs"]:
        if not isinstance(row, dict) or not isinstance(row.get("decision"), dict):
            return None
        found.append(row["decision"].get("reason_code"))
    return found


def s2_flags(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return None
    flags = []
    for row in payload["jobs"]:
        if not isinstance(row, dict):
            return None
        flags.append((
            row.get("decision") is None,
            row.get("decision_error") == "INPUT_INVALID",
            row.get("busy") is True,
        ))
    return flags


def append_mutant(source, wrapper):
    text = source if source.endswith("\n") else source + "\n"
    rewritten = text + "\n" + wrapper
    if not rewritten.endswith("\n"):
        rewritten += "\n"
    compile(rewritten, "<g9-mutant>", "exec")
    return rewritten


def g9_mutants():
    need = miss_detail((SERVE_REL, JOBS_REL, STOP_REL))
    if need:
        return FAIL, need
    doc, err = load_json(JOBS_REL)
    if err:
        return FAIL, err
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    running = coverage_job(jobs, 3) if isinstance(jobs, list) else None
    if running is None:
        return FAIL, "coverage job missing"
    jid = job_id_of(running)
    try:
        source = read_text(REPO_ROOT / STOP_REL)
        ast.parse(source)
    except SyntaxError:
        return FAIL, "stop_policy.py does not parse"
    except (OSError, UnicodeError) as exc:
        return FAIL, "stop_policy.py unreadable: " + type(exc).__name__
    parent = outside_temp_parent()
    if parent is None:
        return BLOCKED, "temp copy failed: no directory outside the repo"
    try:
        holder = tempfile.TemporaryDirectory(prefix="check011-", dir=str(parent))
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__
    with holder:
        pack = Path(holder.name) / "repo"
        try:
            shutil.copytree(REPO_ROOT, pack, ignore=ignore_noise)
        except OSError as exc:
            return BLOCKED, "temp copy failed: " + type(exc).__name__
        dest = pack / STOP_REL
        try:
            if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
                return FAIL, "temp copy aliased the live tree"
        except OSError as exc:
            return BLOCKED, "temp copy failed: " + type(exc).__name__
        baseline, detail = g9_probe(pack, jid)
        if baseline is None:
            return FAIL, "baseline " + detail
        base_list, err = call_of(baseline[0], 0)
        base_tick, err2 = call_of(baseline[0], 1)
        if err or err2:
            return FAIL, "baseline " + (err or err2)
        base_reasons = reason_codes(base_list.get("payload"))
        base_tick_job = base_tick.get("payload").get("job") if isinstance(base_tick.get("payload"), dict) else None
        base_state = base_tick_job.get("state") if isinstance(base_tick_job, dict) else None
        if not base_reasons or base_state is None:
            return FAIL, "baseline shape"
        problems = []
        for name, wrapper in MUTANTS:
            try:
                rewritten = append_mutant(source, wrapper)
            except (SyntaxError, ValueError) as exc:
                return FAIL, name + " could not be installed: " + type(exc).__name__
            try:
                if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
                    return FAIL, "temp copy aliased the live tree"
                dest.write_text(rewritten, encoding="utf-8", newline="\n")
            except OSError as exc:
                return BLOCKED, "mutant write failed: " + type(exc).__name__
            probed, detail = g9_probe(pack, jid)
            if probed is None:
                problems.append(name + " " + detail)
                continue
            if name == "S1":
                listed, err = call_of(probed[0], 0)
                reasons = None if err else reason_codes(listed.get("payload"))
                if err or reasons is None or any(code != "GATE_SENTINEL" for code in reasons) or reasons == base_reasons:
                    problems.append(name + " unchanged" if reasons == base_reasons else name)
            elif name == "S2":
                listed, err = call_of(probed[1], 0)
                ticked, err2 = call_of(probed[1], 1)
                after, err3 = call_of(probed[1], 2)
                flags = None if err else s2_flags(listed.get("payload"))
                before_bits = None if err else snapshot_bits(listed.get("payload"))
                after_bits = None if err3 else snapshot_bits(after.get("payload"))
                payload = ticked.get("payload") if not err2 and isinstance(ticked.get("payload"), dict) else {}
                shape = error_shape(payload) if payload else ["payload"]
                unchanged = listed.get("payload") == base_list.get("payload")
                if (err or err2 or err3 or flags is None or not all(all(item) for item in flags)
                        or ticked.get("status") != 422 or shape or payload.get("reason_code") != "INPUT_INVALID"
                        or before_bits != after_bits or unchanged):
                    problems.append(name + (" unchanged" if unchanged else ""))
            else:
                ticked, err = call_of(probed[0], 1)
                payload = ticked.get("payload") if not err and isinstance(ticked.get("payload"), dict) else {}
                job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
                if err or ticked.get("status") != 200 or job.get("state") != "PAUSED" or job.get("state") == base_state:
                    problems.append(name + (" unchanged" if job.get("state") == base_state else ""))
        if problems:
            return FAIL, cap_text(problems)
        return PASS, "S1 S2 S3"


def header_has_no_store(headers):
    if headers is None:
        return False
    value = headers.get("Cache-Control")
    if value is None:
        return False
    return "no-store" in str(value).lower()


def read_first_line(proc, timeout):
    import selectors
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    data = b""
    end = time.monotonic() + timeout
    try:
        while b"\n" not in data:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return None
            events = selector.select(remaining)
            if not events:
                if proc.poll() is not None:
                    return None
                continue
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                return None
            data += chunk
    finally:
        selector.close()
    return data.split(b"\n", 1)[0].decode("utf-8", "replace").strip("\r")


def stop_proc(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return


def fetch_url(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url)
    end = time.monotonic() + 2
    last = "URLError"
    while True:
        try:
            return opener.open(request, timeout=5), ""
        except urllib.error.URLError as exc:
            last = type(exc).__name__
            if time.monotonic() >= end:
                return None, last
            time.sleep(0.05)


def g10_server():
    need = miss_detail((SERVE_REL, HTML_REL, JS_REL, CSS_REL))
    if need:
        return FAIL, need
    try:
        proc = subprocess.Popen(
            [sys.executable, SERVE_REL, "--port", "0"],
            cwd=str(REPO_ROOT),
            env=child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return BLOCKED, "server could not start: " + type(exc).__name__
    err_box = []

    def drain():
        try:
            err_box.append(proc.stderr.read())
        except Exception:
            err_box.append(b"")

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    problems = []
    try:
        line = read_first_line(proc, 10)
        if proc.poll() not in (None, 0) and line is None:
            return FAIL, "server exit " + str(proc.returncode)
        if line is None:
            return FAIL, "no LISTENING line within 10s"
        match = LISTENING_RE.match(line.strip())
        if match is None:
            return FAIL, "first line " + one_line(line)
        port = int(match.group(1))
        if port <= 0:
            return FAIL, "port " + str(port)
        base = "http://127.0.0.1:" + str(port)
        page, err = fetch_url(base + "/")
        if page is None:
            problems.append("GET / " + err)
        else:
            body = page.read()
            ctype = page.headers.get("Content-Type") or ""
            if page.status != 200:
                problems.append("GET / status " + str(page.status))
            if "text/html" not in ctype.lower():
                problems.append("GET / content-type")
            if not header_has_no_store(page.headers):
                problems.append("GET / cache")
            if "任務列表".encode("utf-8") not in body and "任務列表" not in body.decode("utf-8", "replace"):
                problems.append("GET / job list label")
            page.close()
        for suffix in ("/app.js", "/style.css"):
            resp, err = fetch_url(base + suffix)
            if resp is None:
                problems.append(suffix + " " + err)
                continue
            resp.read()
            if resp.status != 200:
                problems.append(suffix + " status")
            if not header_has_no_store(resp.headers):
                problems.append(suffix + " cache")
            resp.close()
        api, err = fetch_url(base + "/api/jobs")
        if api is None:
            problems.append("/api/jobs " + err)
        else:
            raw = api.read()
            if api.status != 200 or not header_has_no_store(api.headers):
                problems.append("/api/jobs status")
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError):
                parsed = None
            if not isinstance(parsed, dict) or "jobs" not in parsed:
                problems.append("/api/jobs json")
            api.close()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/../serve_local.py")
            resp = conn.getresponse()
            raw = resp.read()
            status_code = resp.status
            cache = resp.getheader("Cache-Control") or ""
            conn.close()
            if status_code != 404:
                problems.append("dotdot status " + str(status_code))
            if "no-store" not in cache.lower():
                problems.append("dotdot cache")
            if b"Traceback" in raw:
                problems.append("dotdot traceback")
        except OSError as exc:
            problems.append("dotdot " + type(exc).__name__)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            raw_body = b"not-json"
            conn.request(
                "POST",
                "/api/reset",
                body=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(raw_body)),
                },
            )
            resp = conn.getresponse()
            raw = resp.read()
            status_code = resp.status
            cache = resp.getheader("Cache-Control") or ""
            conn.close()
            if status_code != 400:
                problems.append("bad json status " + str(status_code))
            if b"Traceback" in raw:
                problems.append("bad json traceback")
            if "no-store" not in cache.lower():
                problems.append("bad json cache")
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError):
                parsed = None
            if not isinstance(parsed, dict) or parsed.get("reason_code") != "BAD_JSON":
                problems.append("bad json reason")
        except OSError as exc:
            problems.append("bad json " + type(exc).__name__)
    finally:
        stop_proc(proc)
        thread.join(timeout=5)
    err_text = b""
    if err_box:
        err_text = err_box[0] or b""
    if b"Traceback" in err_text:
        problems.append("stderr Traceback")
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "listened"


class PageParser:
    def __init__(self, parser):
        self.parser = parser


def parse_page(text):
    import html.parser

    class Collector(html.parser.HTMLParser):
        def __init__(self):
            html.parser.HTMLParser.__init__(self, convert_charrefs=True)
            self.stack = []
            self.roots = []
            self.refs = []

        def handle_starttag(self, tag, attrs):
            attr = {}
            for key, value in attrs:
                attr[key] = value or ""
            for key in ("src", "href"):
                if key in attr:
                    self.refs.append(attr[key].strip())
            node = {"tag": tag, "attr": attr, "parts": []}
            if self.stack:
                self.stack[-1]["parts"].append(("child", node))
            else:
                self.roots.append(node)
            if tag not in VOID_TAGS:
                self.stack.append(node)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index]["tag"] == tag:
                    del self.stack[index:]
                    return

        def handle_data(self, data):
            if self.stack:
                self.stack[-1]["parts"].append(("text", data))

    collector = Collector()
    collector.feed(text)
    collector.close()
    return collector


def iter_nodes(nodes):
    for node in nodes:
        yield node
        for kind, value in node["parts"]:
            if kind == "child":
                for child in iter_nodes([value]):
                    yield child


def text_of(node):
    parts = []
    for kind, value in node["parts"]:
        if kind == "text":
            parts.append(value)
        else:
            parts.append(text_of(value))
    return "".join(parts)


def nodes_with(node, tag):
    found = []

    def walk(current):
        if current["tag"] == tag:
            found.append(current)
        for kind, value in current["parts"]:
            if kind == "child":
                walk(value)

    for kind, value in node["parts"]:
        if kind == "child":
            walk(value)
    return found


def find_id(roots, ident):
    found = []
    for node in iter_nodes(roots):
        if node["attr"].get("id") == ident:
            found.append(node)
    return found


def css_selectors(text):
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    selectors = []
    for block in stripped.split("}"):
        if "{" not in block:
            continue
        selector = block.split("{", 1)[0].strip()
        if selector:
            selectors.append(selector)
    return selectors


def g11_frontend():
    need = miss_detail(PRODUCT_RELS)
    if need:
        return FAIL, need
    problems = []
    try:
        html = read_text(REPO_ROOT / HTML_REL)
        script = read_text(REPO_ROOT / JS_REL)
        style = read_text(REPO_ROOT / CSS_REL)
    except (OSError, UnicodeError) as exc:
        return FAIL, "frontend unreadable: " + type(exc).__name__
    try:
        page = parse_page(html)
    except Exception as exc:
        return FAIL, "html " + type(exc).__name__
    html_nodes = [node for node in iter_nodes(page.roots) if node["tag"] == "html"]
    if len(html_nodes) != 1 or html_nodes[0]["attr"].get("lang") != "zh-Hant":
        problems.append("lang")
    for ref in page.refs:
        if ref not in ("app.js", "style.css") and not ref.startswith("#"):
            problems.append("ref")
            break
    for ident, label in SECTIONS:
        found = find_id(page.roots, ident)
        if len(found) != 1:
            problems.append(ident)
            continue
        if label not in text_of(found[0]):
            problems.append(ident + " label")
    cu = find_id(page.roots, "section-cu")
    if len(cu) == 1 and NOTICE not in text_of(cu[0]):
        problems.append("section-cu notice")
    stop = find_id(page.roots, "section-stop")
    if len(stop) == 1:
        buttons = nodes_with(stop[0], "button")
        pairs = [(button["attr"].get("id"), text_of(button).strip()) for button in buttons]
        if pairs != list(STOP_BUTTONS):
            problems.append("stop buttons")
    onboard = find_id(page.roots, "section-onboarding")
    if len(onboard) == 1:
        lists = nodes_with(onboard[0], "ol")
        items = nodes_with(onboard[0], "li")
        if len(lists) != 1 or len(items) != 3 or len(nodes_with(lists[0], "li")) != 3:
            problems.append("onboarding")
        else:
            texts = [text_of(item) for item in nodes_with(lists[0], "li")]
            if any(word not in text for word, text in zip(ONBOARDING, texts)):
                problems.append("onboarding text")
    for node in iter_nodes(page.roots):
        if node["tag"] == "button" and not has_cjk(text_of(node)):
            problems.append("button text")
            break
    fetch_any = len(FETCH_ANY_RE.findall(script))
    fetch_api = len(FETCH_API_RE.findall(script))
    if fetch_any != fetch_api:
        problems.append("fetch " + str(fetch_any) + "/" + str(fetch_api))
    for banned in BANNED_JS:
        if banned in script:
            problems.append("banned " + banned)
            break
    if "window.confirm(" not in script or "可能遺失未保存產出" not in script:
        problems.append("confirm")
    for code in STATE_CODES + ACTION_CODES:
        if re.search(r"\b" + code + r"\b", script):
            problems.append("code " + code)
            break
    if re.search(r"@import", style, re.IGNORECASE) or re.search(r"url\(", style, re.IGNORECASE):
        problems.append("css import or url")
    selectors = css_selectors(style)
    has_own = any(
        ".state-RELEASE_UNCONFIRMED" in sel and ".state-DONE" not in sel
        for sel in selectors
    )
    shares = any(
        ".state-RELEASE_UNCONFIRMED" in sel and ".state-DONE" in sel
        for sel in selectors
    )
    if not has_own or shares:
        problems.append("css release rule")
    for rel in PRODUCT_RELS:
        problems.extend(hygiene_hits(rel))
    if problems:
        return FAIL, cap_text(problems)
    return PASS, "sections=9"


def g12_regression(before):
    path = REPO_ROOT / "tools/check_010.py"
    if not path.is_file():
        return FAIL, "missing tools/check_010.py"
    proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=180)
    if proc.returncode == 127:
        return BLOCKED, "check_010 could not start"
    line = result_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
    problems = []
    if proc.returncode != 0 or not line.startswith("RESULT: ALL PASS"):
        problems.append("check_010 exit " + str(proc.returncode) + " " + one_line(line))
    changed = blob_changes(before, live_blobs())
    if changed:
        shown = ",".join(changed[:8])
        extra = "" if len(changed) <= 8 else " +" + str(len(changed) - 8)
        problems.append("live blobs changed: " + shown + extra)
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "check_010 exit 0"


def run_gate(title, func):
    try:
        status, detail = func()
    except Exception as exc:
        status, detail = FAIL, "internal " + type(exc).__name__ + ": " + str(exc)
    gate(title, status, detail)


def main():
    del FAILURES[:]
    before = live_blobs()
    run_gate(
        "G1 five files exist; serve_local HOST, names, decide import, whitelist, and silent import",
        g1_shape,
    )
    run_gate(
        "G2 STATE_LABELS, BUSY_STATES, and state_view match the 15 codes",
        g2_states,
    )
    run_gate(
        "G3 jobs.json matches R3, decide accepts every job, and the file is hygienic",
        g3_fixture,
    )
    run_gate(
        "G4 handle list, detail, cu, release, blocker, and errors match R4",
        g4_api,
    )
    run_gate(
        "G5 tick and the four commands apply only through decide",
        g5_apply,
    )
    run_gate(
        "G6 human hold and stop_now confirmation",
        g6_hold,
    )
    run_gate(
        "G7 bot port keys, refusals, and credential sentinel",
        g7_bot,
    )
    run_gate(
        "G8 each POST adds one audit, reset leaves one RESET, detail lists that job",
        g8_audit,
    )
    run_gate(
        "G9 temp-copy mutants S1 S2 S3 change serve_local",
        g9_mutants,
    )
    run_gate(
        "G10 live server on 127.0.0.1 answers static, API, dotdot, and bad JSON",
        g10_server,
    )
    run_gate(
        "G11 static page, script, stylesheet, and hygiene of the five files",
        g11_frontend,
    )
    run_gate(
        "G12 check_010.py exits 0 and live file hashes are unchanged",
        lambda: g12_regression(before),
    )
    print("", flush=True)
    if FAILURES:
        print(
            "RESULT: FAIL (" + str(len(FAILURES)) + " block-level gate(s)): "
            + "; ".join(one_line(name) for name in FAILURES),
            flush=True,
        )
        return 1
    print("RESULT: ALL PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
