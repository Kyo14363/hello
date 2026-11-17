#!/usr/bin/env python3
"""check_012 - routine scripts gate for work order 012.

Written before routines/. G1-G10 are expected red until the five
routines/ files exist. G11 is red too while daily_file_presence.py is
missing.

Stdlib only, offline, ASCII stdout. The live tree is read only.
Mutations are appended on a temp copy. Every child gets
PYTHONIOENCODING=utf-8 and PYTHONDONTWRITEBYTECODE=1, has PYTHONPATH
removed, then PYTHONPATH set to routines (regression gates clear it).

A6 entries are constants here. This script does not read the spec
while it runs. Script A is only pointed at --input-file or at
127.0.0.1.

Each check prints [PASS], [FAIL], or [BLOCKED]. Exit 0 only when every
one is PASS. BLOCKED means the interpreter did not start or a temp copy
could not be made. A missing product file is FAIL. The mode-000 case
prints [BLOCKED] when the process is root and that line is not a failure.
"""

import os
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import ast
import datetime
import hashlib
import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

A_REL = "routines/changelog_version_check.py"
B_REL = "routines/daily_file_presence.py"
FIX_REL = "routines/fixtures/changelog_sample.html"
TEST_A_REL = "routines/tests/test_changelog_version_check.py"
TEST_B_REL = "routines/tests/test_daily_file_presence.py"
PRODUCT_RELS = (A_REL, B_REL, FIX_REL, TEST_A_REL, TEST_B_REL)
SCRIPTS = (A_REL, B_REL)
MIN_TESTS = 16

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
FAILURES = []
TRACKED = []

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)
HASH_SKIP = {".git", "__pycache__"}
COPY_SKIP = {".git", "__pycache__", ".venv", "venv"}

PAGE_VERSION = "v2.10.0"
PAGE_DATE = "2026-01-20"
A_KEYS = {"version", "date", "changed", "new_entries", "error"}
B_KEYS = {"date", "files", "status", "first_present", "missing", "error"}
FILE_KEYS = {"order", "path", "exists", "mtime"}
ENTRY_KEYS = {"version", "section", "text"}
MTIME_STAMP = 1768900000
MTIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")
JST = datetime.timezone(datetime.timedelta(hours=9))
RUN_DATE = "2026-01-20"
PAT_A = "a/report-{YYYY-MM-DD}.json"
PAT_B = "b/report_{YYYYMMDD}.md"
REL_A = "a/report-2026-01-20.json"
REL_B = "b/report_20260120.md"
YREL_A = "a/report-2026-01-19.json"
YREL_B = "b/report_20260119.md"
TEXT_FAIL = "Changelog 本次未能讀取"
RAN_RE = re.compile(r"^Ran (\d+) tests?\b", re.MULTILINE)
SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]*")
PRIVATE_PATH_RE = re.compile(
    r"(?:/home/|/Users/|(?:^|[^A-Za-z0-9_])[A-Za-z]:[\\/])"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TOKEN_RES = (
    ("github token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("key token", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws token", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt", re.compile(
        r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    )),
    ("assigned secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|refresh[_-]?token|password)\b"
        r"\s*[:=]\s*['\"][^'\"]{6,}['\"]"
    )),
    ("bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
)
HTTP_OK = (
    re.compile(r"https://example\.invalid(?:/.*)?\Z", re.IGNORECASE),
    re.compile(r"http://127\.0\.0\.1:\d+(?:/.*)?\Z"),
)
OTHER_OK = (
    re.compile(r"file://\S*\Z", re.IGNORECASE),
    re.compile(r"ftp://example\.invalid(?:/.*)?\Z", re.IGNORECASE),
)

# str.replace stays legal: B1 expands placeholders by string substitution.
# replace here means the filesystem call (os.replace / a bare replace()).
FS_ATTRS = frozenset({
    "write_text", "write_bytes", "mkdir", "makedirs", "remove", "unlink",
    "rename", "rmdir", "chmod",
})
B_EXTRA_ATTRS = frozenset({
    "read_text", "read_bytes", "listdir", "scandir", "glob", "iterdir", "walk",
})
FALLBACK_STDLIB = frozenset({
    "__future__", "abc", "argparse", "ast", "base64", "binascii", "bisect",
    "builtins", "calendar", "collections", "contextlib", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "enum", "errno", "fnmatch",
    "fractions", "functools", "getopt", "glob", "gzip", "hashlib", "heapq",
    "html", "http", "importlib", "io", "ipaddress", "itertools", "json",
    "math", "numbers", "operator", "os", "pathlib", "platform", "posixpath",
    "pprint", "random", "re", "shlex", "shutil", "signal", "socket", "stat",
    "string", "struct", "subprocess", "sys", "tempfile", "textwrap", "time",
    "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
    "weakref", "zipfile",
})


def entry(version, section, text):
    return {"version": version, "section": section, "text": text}


NEW_210 = (
    entry("v2.10.0", "New", "Calendar sync now runs every 5 minutes."),
    entry("v2.10.0", "New", "Search & filters load twice as fast. Beta"),
    entry("v2.10.0", "Fixed", "Fixed a crash when a list was empty."),
)
NEW_291 = (
    entry("v2.9.1", "Improved", "Settings page remembers the last tab."),
    entry("v2.9.1", "Fixed", "Fixed dates showing in the wrong order."),
)
FIVE = NEW_210 + NEW_291


def text_ok(version, date):
    return "Changelog 最新：" + version + "（" + date + "，本次讀網頁確認）"


def entry_line(item):
    return "- [" + item["version"] + "] " + item["section"] + ": " + item["text"]


M1_SRC = """
_gate012_m1_main = main


def _gate012_m1_prev(argv):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    found = False
    prev = ""
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--previous-version" and index + 1 < len(args):
            prev = args[index + 1]
            found = True
            break
        if item.startswith("--previous-version="):
            prev = item.split("=", 1)[1]
            found = True
            break
        index += 1
    return found, prev


def main(argv=None):
    import io
    import json
    import sys
    found, prev = _gate012_m1_prev(argv)
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        code = _gate012_m1_main(argv)
    finally:
        sys.stdout = real
    text = buf.getvalue()
    if code != 2 or not found:
        sys.stdout.write(text)
        return code
    lines = text.splitlines(keepends=True)
    if not lines:
        sys.stdout.write(text)
        return code
    raw = lines[0]
    ending = ""
    if raw.endswith("\\r\\n"):
        ending = "\\r\\n"
        raw = raw[:-2]
    elif raw.endswith("\\n"):
        ending = "\\n"
        raw = raw[:-1]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        sys.stdout.write(text)
        return code
    if not isinstance(doc, dict):
        sys.stdout.write(text)
        return code
    doc["version"] = prev
    lines[0] = json.dumps(doc, ensure_ascii=True, sort_keys=True) + ending
    sys.stdout.write("".join(lines))
    return code
"""

M2_SRC = """
_gate012_m2_main = main


def _gate012_m2_prev(argv):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--previous-version" and index + 1 < len(args):
            return args[index + 1]
        if item.startswith("--previous-version="):
            return item.split("=", 1)[1]
        index += 1
    return ""


def _gate012_m2_tuple(text):
    body = text[1:] if text.startswith("v") else text
    parts = body.split(".")
    if len(parts) != 3:
        return None
    nums = []
    for part in parts:
        if not part.isdigit():
            return None
        nums.append(int(part))
    return tuple(nums)


def main(argv=None):
    import io
    import json
    import sys
    prev = _gate012_m2_prev(argv)
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        code = _gate012_m2_main(argv)
    finally:
        sys.stdout = real
    text = buf.getvalue()
    if code not in (0, 10):
        sys.stdout.write(text)
        return code
    lines = text.splitlines(keepends=True)
    if not lines:
        sys.stdout.write(text)
        return code
    raw = lines[0]
    ending = ""
    if raw.endswith("\\r\\n"):
        ending = "\\r\\n"
        raw = raw[:-2]
    elif raw.endswith("\\n"):
        ending = "\\n"
        raw = raw[:-1]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        sys.stdout.write(text)
        return code
    version = doc.get("version") if isinstance(doc, dict) else None
    page = _gate012_m2_tuple(version) if isinstance(version, str) else None
    old = _gate012_m2_tuple(prev) if isinstance(prev, str) and prev else None
    if page is None or old is None:
        sys.stdout.write(text)
        return code
    shown = version if version.startswith("v") else "v" + version
    prev_shown = prev if prev.startswith("v") else "v" + prev
    string_newer = shown > prev_shown
    numeric_newer = page > old
    if string_newer == numeric_newer:
        sys.stdout.write(text)
        return code
    if string_newer:
        doc["changed"] = True
        doc["new_entries"] = []
        doc["error"] = None
        code = 10
    else:
        doc["changed"] = False
        doc["new_entries"] = []
        doc["error"] = None
        code = 0
        if len(lines) > 2:
            lines = lines[:2]
    lines[0] = json.dumps(doc, ensure_ascii=True, sort_keys=True) + ending
    sys.stdout.write("".join(lines))
    return code
"""

M3_SRC = """
_gate012_m3_main = main


def _gate012_m3_opts(argv):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    root = None
    date = None
    patterns = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--root" and index + 1 < len(args):
            root = args[index + 1]
            index += 2
            continue
        if item.startswith("--root="):
            root = item.split("=", 1)[1]
            index += 1
            continue
        if item == "--date" and index + 1 < len(args):
            date = args[index + 1]
            index += 2
            continue
        if item.startswith("--date="):
            date = item.split("=", 1)[1]
            index += 1
            continue
        if item == "--pattern" and index + 1 < len(args):
            patterns.append(args[index + 1])
            index += 2
            continue
        if item.startswith("--pattern="):
            patterns.append(item.split("=", 1)[1])
            index += 1
            continue
        index += 1
    return root, date, patterns


def main(argv=None):
    import io
    import json
    import sys
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    root, date, patterns = _gate012_m3_opts(argv)
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        code = _gate012_m3_main(argv)
    finally:
        sys.stdout = real
    text = buf.getvalue()
    lines = text.splitlines(keepends=True)
    if not lines:
        sys.stdout.write(text)
        return code
    raw = lines[0]
    ending = ""
    if raw.endswith("\\r\\n"):
        ending = "\\r\\n"
        raw = raw[:-2]
    elif raw.endswith("\\n"):
        ending = "\\n"
        raw = raw[:-1]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        sys.stdout.write(text)
        return code
    files = doc.get("files") if isinstance(doc, dict) else None
    if (not isinstance(files, list) or not files or not isinstance(files[0], dict)
            or files[0].get("exists") is not False or not root or not patterns):
        sys.stdout.write(text)
        return code
    if not date:
        date = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date() - timedelta(days=1)
    except ValueError:
        sys.stdout.write(text)
        return code
    iso = day.isoformat()
    compact = iso.replace("-", "")
    rel = patterns[0].replace("{YYYY-MM-DD}", iso).replace("{YYYYMMDD}", compact)
    target = Path(root) / rel
    try:
        present = target.is_file()
    except OSError:
        present = False
    if not present:
        sys.stdout.write(text)
        return code
    files[0]["exists"] = True
    files[0]["mtime"] = "2000-01-01T00:00:00+09:00"
    flags = []
    for item in files:
        if isinstance(item, dict):
            flags.append(bool(item.get("exists")))
        else:
            flags.append(False)
    if all(flags):
        doc["status"] = "all"
    elif any(flags):
        doc["status"] = "partial"
    else:
        doc["status"] = "missing"
    first = None
    missing = []
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("exists") and first is None:
            first = item.get("path")
        if not item.get("exists"):
            missing.append(item.get("path"))
    doc["first_present"] = first
    doc["missing"] = missing
    doc["error"] = None
    lines[0] = json.dumps(doc, ensure_ascii=True, sort_keys=True) + ending
    sys.stdout.write("".join(lines))
    return 0 if any(flags) else 3
"""

MUTANTS = (
    ("M1", A_REL, M1_SRC),
    ("M2", A_REL, M2_SRC),
    ("M3", B_REL, M3_SRC),
)

URL_PROBE = r"""
import io
import json
import sys
import urllib.request

calls = []


def boom(*args, **kwargs):
    calls.append(1)
    raise OSError("blocked")


urllib.request.urlopen = boom
real_out = sys.stdout
real_err = sys.stderr
sys.stdout = io.StringIO()
sys.stderr = io.StringIO()
import changelog_version_check
sys.stdout = real_out
sys.stderr = real_err

buf = io.StringIO()
sys.stdout = buf
error = ""
try:
    code = changelog_version_check.main([
        "--url", "file:///etc/hostname",
        "--previous-version", "v1.0.0",
    ])
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 2
except Exception as exc:
    code = 1
    error = type(exc).__name__
finally:
    sys.stdout = real_out

sys.stdout.write(json.dumps({
    "code": code,
    "stdout": buf.getvalue(),
    "calls": len(calls),
    "error": error,
}, ensure_ascii=True))
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


def note_blocked(name, detail):
    print("[BLOCKED] " + one_line(name) + " -- " + one_line(detail), flush=True)


def child_env(extra=None, pythonpath="routines"):
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    if extra:
        for key, value in extra.items():
            env[str(key)] = str(value)
    return env


def run_process(argv, cwd, timeout=60, extra_env=None, pythonpath="routines"):
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(extra_env, pythonpath=pythonpath),
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


def tail(proc, n=200):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text[-n:]


def join_bits(parts, limit=8):
    if len(parts) <= limit:
        return "; ".join(parts)
    return "; ".join(parts[:limit]) + "; +" + str(len(parts) - limit) + " more"


def missing_rels(rels):
    missing = []
    for rel in rels:
        if not (REPO_ROOT / rel).is_file():
            missing.append(rel)
    return missing


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def stdlib_names():
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return set(FALLBACK_STDLIB)


def unique(items):
    found = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            found.append(item)
    return found


def live_blobs(root=None):
    root = Path(REPO_ROOT if root is None else root)
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in HASH_SKIP]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                found[rel] = "unreadable"
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


def make_temp(prefix):
    parent = outside_temp_parent()
    if parent is None:
        return None, BLOCKED, "no directory outside the repo"
    try:
        holder = tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent))
    except OSError as exc:
        return None, BLOCKED, "temp dir " + type(exc).__name__
    path = Path(holder.name)
    try:
        if path.resolve().is_relative_to(REPO_ROOT.resolve()):
            holder.cleanup()
            return None, FAIL, "temp dir landed in the live tree"
    except OSError as exc:
        holder.cleanup()
        return None, BLOCKED, "temp dir " + type(exc).__name__
    return holder, None, ""


def run_tracked(argv, cwd, temps=(), extra_env=None, timeout=30, pythonpath="routines"):
    before_repo = live_blobs(REPO_ROOT)
    before_temps = []
    for temp in temps:
        temp = Path(temp)
        before_temps.append((temp, live_blobs(temp)))
    proc = run_process(
        argv, cwd, timeout=timeout, extra_env=extra_env, pythonpath=pythonpath)
    problems = []
    changed = blob_changes(before_repo, live_blobs(REPO_ROOT))
    if changed:
        problems.append("repo " + ",".join(changed[:6]))
    for temp, before in before_temps:
        if not Path(temp).exists():
            problems.append("temp disappeared")
            continue
        changed = blob_changes(before, live_blobs(temp))
        if changed:
            problems.append("temp " + ",".join(changed[:6]))
    TRACKED.append(problems)
    return proc


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("non-string key")
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def parse_json_line(line):
    try:
        line.encode("ascii")
    except UnicodeEncodeError:
        return None, "json line is not ascii"
    try:
        doc = json.loads(line, object_pairs_hook=strict_object)
    except ValueError as exc:
        return None, "json " + type(exc).__name__
    if not isinstance(doc, dict):
        return None, "json is not an object"
    canonical = json.dumps(doc, ensure_ascii=True, sort_keys=True)
    if line != canonical:
        return None, "json line is not canonical"
    return doc, ""


def stdout_docs(text, count):
    lines = (text or "").splitlines()
    if len(lines) != count:
        return None, lines, "stdout lines " + str(len(lines))
    doc, problem = parse_json_line(lines[0])
    if problem:
        return None, lines, problem
    return doc, lines, ""


def is_root():
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def expected_mtime(stamp):
    when = datetime.datetime.fromtimestamp(stamp, tz=JST)
    return when.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"


def a_argv(extra):
    return [sys.executable, A_REL, *extra]


def b_argv(root, patterns, date=RUN_DATE, extra=()):
    argv = [sys.executable, B_REL, "--root", str(root), "--date", date]
    for pattern in patterns:
        argv.extend(["--pattern", pattern])
    argv.extend(extra)
    return argv


def run_a(args, temps=(), timeout=20):
    return run_tracked(a_argv(args), REPO_ROOT, temps=temps, timeout=timeout)


def file_row(order, path, exists, mtime):
    return {"order": order, "path": path, "exists": exists, "mtime": mtime}


def b_doc(status, first, missing, rows):
    return {
        "date": RUN_DATE,
        "files": rows,
        "status": status,
        "first_present": first,
        "missing": missing,
        "error": None,
    }


def both_rows(mtime):
    return (
        file_row(1, REL_A, True, mtime),
        file_row(2, REL_B, True, mtime),
    )


def only_first_rows(mtime):
    return (
        file_row(1, REL_A, True, mtime),
        file_row(2, REL_B, False, None),
    )


def only_second_rows(mtime):
    return (
        file_row(1, REL_A, False, None),
        file_row(2, REL_B, True, mtime),
    )


def neither_rows():
    return (
        file_row(1, REL_A, False, None),
        file_row(2, REL_B, False, None),
    )


def value_type_ok(got, expect):
    if expect is None:
        return got is None
    if isinstance(expect, bool):
        return type(got) is bool and got is expect
    if isinstance(expect, int) and not isinstance(expect, bool):
        return type(got) is int and got == expect
    if isinstance(expect, str):
        return isinstance(got, str) and got == expect
    if isinstance(expect, list):
        if not isinstance(got, list) or len(got) != len(expect):
            return False
        return all(value_type_ok(left, right) for left, right in zip(got, expect))
    if isinstance(expect, dict):
        if not isinstance(got, dict) or set(got) != set(expect):
            return False
        return all(value_type_ok(got[key], expect[key]) for key in expect)
    return got == expect


def a_success(doc, changed, entries):
    expect = {
        "version": PAGE_VERSION,
        "date": PAGE_DATE,
        "changed": changed,
        "new_entries": [dict(item) for item in entries],
        "error": None,
    }
    if set(doc) != A_KEYS:
        return False
    return value_type_ok(doc, expect)


def a_error(doc, prefix, previous):
    if set(doc) != A_KEYS:
        return False
    if doc.get("version") is not None or doc.get("version") == previous:
        return False
    if doc.get("date") is not None:
        return False
    if doc.get("changed") is not False:
        return False
    if doc.get("new_entries") != []:
        return False
    error = doc.get("error")
    return isinstance(error, str) and error.startswith(prefix) and error != ""


def plant(root, rels, stamp):
    root = Path(root)
    note = root / "a" / "note.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    if not note.exists():
        note.write_text("note\n", encoding="utf-8")
    for rel in rels:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
        os.utime(path, (stamp, stamp))


def closed_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def serve_fixture(payload):
    seen = {"agent": None, "path": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["agent"] = self.headers.get("User-Agent")
            seen["path"] = self.path.split("?", 1)[0]
            body = payload
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, httpd.server_address[1], seen


def stop_server(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def base_name(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def open_problem(call):
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            return "open mode not constant"
    for kw in call.keywords:
        if kw.arg is None:
            return "open mode not constant"
    mode = None
    saw = False
    if len(call.args) >= 2:
        saw = True
        mode = const_str(call.args[1])
        if mode is None:
            return "open mode not constant"
    for kw in call.keywords:
        if kw.arg == "mode":
            saw = True
            mode = const_str(kw.value)
            if mode is None:
                return "open mode not constant"
    if not saw:
        return None
    if mode is not None and any(ch in mode for ch in "wax+"):
        return "open write mode"
    return None


def call_issues(tree, script_b):
    banned = set(FS_ATTRS)
    if script_b:
        banned.update(B_EXTRA_ATTRS)
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            attr = func.id
            base = None
        elif isinstance(func, ast.Attribute):
            attr = func.attr
            base = base_name(func.value)
        else:
            continue
        if base in ("shutil", "tempfile") or (script_b and base == "zoneinfo"):
            issues.append(base + " call")
            continue
        if attr == "open":
            if script_b:
                issues.append("open")
            else:
                problem = open_problem(node)
                if problem:
                    issues.append(problem)
            continue
        if attr == "replace":
            if base in ("os", "shutil", "pathlib") or isinstance(func, ast.Name):
                issues.append("replace")
            continue
        if attr in banned:
            issues.append(attr)
    return unique(issues)


def import_issues(tree, script_b):
    banned = {"shutil", "tempfile"}
    if script_b:
        banned.update(("zoneinfo", "glob"))
    allowed = stdlib_names()
    issues = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                issues.append("relative import")
                continue
            modules = [node.module or ""]
        else:
            continue
        for mod in modules:
            top = mod.split(".", 1)[0]
            if not top:
                issues.append("import ?")
            elif top in banned:
                issues.append("import " + top)
            elif top not in allowed:
                issues.append("import " + top)
    return unique(issues)


def has_main(tree):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return True
    return False


def string_env(tree):
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            value = const_str(node.value)
            if value is not None:
                found[target.id] = value
    return found


def literal_string(node, env):
    value = const_str(node)
    if value is not None:
        return value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    return None


def pattern_calls(tree):
    env = string_env(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if name != "add_argument":
            continue
        strings = []
        for arg in node.args:
            text = literal_string(arg, env)
            if text is not None:
                strings.append(text)
        if "--pattern" in strings:
            found.append(node)
    return found


def hardcoded_pattern(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if ("{YYYY-MM-DD}" in text or "{YYYYMMDD}" in text) and (
                "/" in text or "\\" in text):
            return True
    return False


def pattern_structure(tree):
    # G11 checks structure only.
    problems = []
    calls = pattern_calls(tree)
    if not calls:
        problems.append("no --pattern argument")
    for call in calls:
        required = None
        has_default = False
        for kw in call.keywords:
            if kw.arg == "required":
                required = kw.value
            elif kw.arg == "default":
                has_default = True
        if has_default:
            problems.append("--pattern has default=")
        if not (isinstance(required, ast.Constant) and required.value is True):
            problems.append("--pattern is not required=True")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else ""
        if name != "set_defaults":
            continue
        for kw in node.keywords:
            if kw.arg in ("pattern", "patterns"):
                problems.append("set_defaults " + kw.arg)
    if hardcoded_pattern(tree):
        problems.append("hard-coded path pattern")
    return unique(problems)


def ran_count(text):
    found = RAN_RE.findall(text or "")
    if not found:
        return None
    return int(found[-1])


def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def unittest_argv():
    return [sys.executable, "-m", "unittest", "discover", "-s", "routines/tests"]


def append_mutant(source, wrapper):
    text = source
    if not text.endswith("\n"):
        text += "\n"
    rewritten = text + "\n" + wrapper
    if not rewritten.endswith("\n"):
        rewritten += "\n"
    compile(rewritten, "<g9-mutant>", "exec")
    return rewritten


def hygiene_hit(rel, line):
    if EMAIL_RE.search(line):
        return "email"
    if PRIVATE_PATH_RE.search(line):
        return "absolute path"
    for name, pattern in TOKEN_RES:
        if pattern.search(line):
            return name
    urls = SCHEME_RE.findall(line)
    if rel in SCRIPTS and urls:
        return "hardcoded url"
    for url in urls:
        if any(item.search(url) for item in HTTP_OK):
            continue
        if any(item.search(url) for item in OTHER_OK):
            continue
        return "url"
    return None


def hygiene_problems():
    hits = []
    for rel in PRODUCT_RELS:
        path = REPO_ROOT / rel
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            return [rel + " unreadable: " + type(exc).__name__]
        for number, line in enumerate(text.splitlines(), 1):
            kind = hygiene_hit(rel, line)
            if kind:
                hits.append(rel + ":" + str(number) + " " + kind)
                if len(hits) >= 8:
                    return hits
    return hits


def load_tree(rel):
    path = REPO_ROOT / rel
    try:
        source = read_text(path)
        return ast.parse(source), source, ""
    except SyntaxError as exc:
        return None, "", rel + " does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return None, "", rel + " unreadable: " + type(exc).__name__


def import_probe(module):
    before = live_blobs(REPO_ROOT)
    proc = run_process(
        [sys.executable, "-c", "import " + module], REPO_ROOT, timeout=30)
    changed = blob_changes(before, live_blobs(REPO_ROOT))
    return proc, changed


def g1_shape():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    problems = []
    for rel, module in ((A_REL, "changelog_version_check"), (B_REL, "daily_file_presence")):
        tree, _source, problem = load_tree(rel)
        if problem:
            problems.append(problem)
            continue
        if not has_main(tree):
            problems.append(rel + " has no main")
        problems.extend(rel + " " + item for item in import_issues(tree, rel == B_REL))
        proc, changed = import_probe(module)
        if proc.returncode == 127:
            return BLOCKED, module + " could not start"
        if proc.returncode != 0:
            problems.append(module + " import exit " + str(proc.returncode))
        if (proc.stdout or "") != "":
            problems.append(module + " stdout not empty")
        if (proc.stderr or "") != "":
            problems.append(module + " stderr not empty")
        if changed:
            problems.append(module + " import wrote " + ",".join(changed[:4]))
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "files=5 import_silent=True"


def g2_static():
    missing = missing_rels(SCRIPTS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    problems = []
    for rel in SCRIPTS:
        tree, _source, problem = load_tree(rel)
        if problem:
            problems.append(problem)
            continue
        script_b = rel == B_REL
        kept = list(call_issues(tree, script_b))
        for item in import_issues(tree, script_b):
            if item.startswith("import shutil") or item.startswith("import tempfile"):
                kept.append(item)
            elif item == "relative import":
                kept.append(item)
            elif script_b and (
                    item.startswith("import zoneinfo") or item.startswith("import glob")):
                kept.append(item)
        problems.extend(rel + " " + item for item in unique(kept))
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "scripts=2"


def case_problems(proc, changed, entries, previous):
    problems = []
    if proc.returncode == 127:
        return ["could not start"]
    if proc.returncode == 124:
        return ["timeout"]
    if proc.returncode != (10 if changed else 0):
        problems.append("exit " + str(proc.returncode))
    if (proc.stderr or "") != "":
        problems.append("stderr")
    doc, _lines, problem = stdout_docs(proc.stdout or "", 1)
    if problem:
        problems.append(problem)
    elif not a_success(doc, changed, entries):
        problems.append("body for " + previous)
    return problems


def g3_behavior():
    missing = missing_rels((A_REL, FIX_REL))
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    cases = (
        ("v2.10.0", False, ()),
        ("v2.9.1", True, NEW_210),
        ("2.9.0", True, FIVE),
        ("v2.9.10", True, NEW_210),
        ("v3.0.0", False, ()),
    )
    problems = []
    for previous, changed, entries in cases:
        proc = run_a([
            "--input-file", FIX_REL,
            "--previous-version", previous,
        ])
        bits = case_problems(proc, changed, entries, previous)
        if bits:
            problems.append(previous + " " + ",".join(bits))
    try:
        payload = (REPO_ROOT / FIX_REL).read_bytes()
    except OSError as exc:
        return FAIL, "fixture unreadable: " + type(exc).__name__
    try:
        httpd, thread, port, seen = serve_fixture(payload)
    except OSError as exc:
        return FAIL, "local server " + type(exc).__name__
    try:
        url = "http://127.0.0.1:" + str(port) + "/changelog_sample.html"
        proc = run_a([
            "--url", url,
            "--previous-version", "v2.9.1",
            "--timeout", "5",
        ], timeout=20)
        bits = case_problems(proc, True, NEW_210, "v2.9.1")
        if bits:
            problems.append("local url " + ",".join(bits))
        if seen.get("agent") != "hello-routines/1":
            problems.append("user-agent " + repr(seen.get("agent")))
        if seen.get("path") != "/changelog_sample.html":
            problems.append("request path")
    finally:
        stop_server(httpd, thread)
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "cases=5 local_server=match"


def error_case(args, prefix, previous, text_line, temps):
    proc = run_a(args, temps=temps, timeout=20)
    problems = []
    if proc.returncode == 127:
        return ["could not start"]
    if proc.returncode == 124:
        return ["timeout"]
    if proc.returncode != 2:
        problems.append("exit " + str(proc.returncode))
    if (proc.stderr or "") != "":
        problems.append("stderr")
    count = 2 if text_line else 1
    doc, lines, problem = stdout_docs(proc.stdout or "", count)
    if problem:
        problems.append(problem)
        return problems
    if not a_error(doc, prefix, previous):
        problems.append("body " + prefix)
    if text_line and (len(lines) != 2 or lines[1] != TEXT_FAIL):
        problems.append("text line")
    return problems


def g4_unreadable():
    if missing_rels((A_REL,)):
        return FAIL, "missing " + A_REL
    holder, status, detail = make_temp("check012-a-")
    if holder is None:
        return status, detail
    problems = []
    with holder:
        empty = Path(holder.name) / "empty.html"
        bait = Path(holder.name) / "bait.html"
        try:
            empty.write_bytes(b"")
            bait.write_text(
                "<!DOCTYPE html><html><body><h2 id=\"v9.9.9\">bait</h2></body></html>\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return BLOCKED, "fixture write " + type(exc).__name__
        port = closed_port()
        closed = "http://127.0.0.1:" + str(port) + "/"
        runs = (
            ("closed", ["--url", closed, "--previous-version", "v1.0.0", "--timeout", "3"],
             "fetch_failed", "v1.0.0"),
            ("file", ["--url", "file:///etc/hostname", "--previous-version", "v1.0.0"],
             "bad_url", "v1.0.0"),
            ("empty", ["--input-file", str(empty), "--previous-version", "v1.0.0"],
             "parse_failed", "v1.0.0"),
            ("bait", ["--input-file", str(bait), "--previous-version", "v1.0.0"],
             "parse_failed", "v1.0.0"),
        )
        for name, args, prefix, previous in runs:
            for text_line in (False, True):
                use = list(args)
                if text_line:
                    use.append("--text-line")
                bits = error_case(use, prefix, previous, text_line, (holder.name,))
                if bits:
                    label = name + ("+text" if text_line else "")
                    problems.append(label + " " + ",".join(bits))
        probe_path = Path(holder.name) / "url_probe.py"
        try:
            compile(URL_PROBE, "<url-probe>", "exec")
            probe_path.write_text(URL_PROBE, encoding="utf-8", newline="\n")
        except (OSError, SyntaxError) as exc:
            return FAIL, "url probe " + type(exc).__name__
        proc = run_tracked(
            [sys.executable, str(probe_path)], REPO_ROOT, temps=(holder.name,), timeout=20)
        if proc.returncode != 0:
            problems.append("urlopen probe exit " + str(proc.returncode))
        else:
            try:
                got = json.loads(proc.stdout or "")
            except ValueError:
                got = None
            if not isinstance(got, dict):
                problems.append("urlopen probe stdout")
            elif got.get("calls") != 0 or got.get("code") != 2:
                problems.append(
                    "urlopen calls=" + str(got.get("calls"))
                    + " code=" + str(got.get("code"))
                )
            else:
                doc, _lines, problem = stdout_docs(got.get("stdout") or "", 1)
                if problem or not a_error(doc, "bad_url", "v1.0.0"):
                    problems.append("urlopen probe body")
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "closed=fetch_failed file=bad_url empty=parse_failed"


def g5_text():
    missing = missing_rels((A_REL, FIX_REL))
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    expect = (
        ("v2.10.0", False, (), [text_ok(PAGE_VERSION, PAGE_DATE)]),
        ("v3.0.0", False, (), [text_ok(PAGE_VERSION, PAGE_DATE)]),
        ("v2.9.1", True, NEW_210, [text_ok(PAGE_VERSION, PAGE_DATE)] + [
            entry_line(item) for item in NEW_210
        ]),
    )
    problems = []
    for previous, changed, entries, extra in expect:
        proc = run_a([
            "--input-file", FIX_REL,
            "--previous-version", previous,
            "--text-line",
        ])
        if proc.returncode != (10 if changed else 0):
            problems.append(previous + " exit " + str(proc.returncode))
            continue
        if (proc.stderr or "") != "":
            problems.append(previous + " stderr")
        doc, lines, problem = stdout_docs(proc.stdout or "", 1 + len(extra))
        if problem:
            problems.append(previous + " " + problem)
            continue
        if not a_success(doc, changed, entries):
            problems.append(previous + " body")
        if lines[1:] != extra:
            problems.append(previous + " text")
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "lines=0,0,10"


def b_problems(proc, expect, code, root_text):
    problems = []
    if proc.returncode == 127:
        return ["could not start"]
    if proc.returncode == 124:
        return ["timeout"]
    if proc.returncode != code:
        problems.append("exit " + str(proc.returncode))
    if (proc.stderr or "") != "":
        problems.append("stderr")
    text = proc.stdout or ""
    if root_text and root_text in text:
        problems.append("root leaked")
    doc, _lines, problem = stdout_docs(text, 1)
    if problem:
        problems.append(problem)
    elif not value_type_ok(doc, expect):
        problems.append("body")
    return problems


def g6_presence():
    if missing_rels((B_REL,)):
        return FAIL, "missing " + B_REL
    holder, status, detail = make_temp("check012-b-")
    if holder is None:
        return status, detail
    mtime = expected_mtime(MTIME_STAMP)
    problems = []
    blocked_note = None
    with holder:
        root = Path(holder.name)
        root_text = str(root)
        patterns = (PAT_A, PAT_B)
        cases = (
            ("all", (REL_A, REL_B), 0, b_doc("all", REL_A, [], list(both_rows(mtime)))),
            ("first", (REL_A,), 0, b_doc("partial", REL_A, [REL_B], list(only_first_rows(mtime)))),
            ("second", (REL_B,), 0, b_doc("partial", REL_B, [REL_A], list(only_second_rows(mtime)))),
            ("none", (), 3, b_doc("missing", None, [REL_A, REL_B], list(neither_rows()))),
            ("yesterday", (YREL_A, YREL_B), 3, b_doc(
                "missing", None, [REL_A, REL_B], list(neither_rows()))),
        )
        for name, rels, code, expect in cases:
            try:
                for child in root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                plant(root, rels, MTIME_STAMP)
            except OSError as exc:
                return BLOCKED, "fixture " + type(exc).__name__
            proc = run_tracked(
                b_argv(root, patterns), REPO_ROOT, temps=(root,), timeout=20)
            bits = b_problems(proc, expect, code, root_text)
            if bits:
                problems.append(name + " " + ",".join(bits))
        try:
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            plant(root, (REL_A, REL_B), MTIME_STAMP)
        except OSError as exc:
            return BLOCKED, "fixture " + type(exc).__name__
        tz_docs = []
        for zone in ("UTC", "America/New_York"):
            proc = run_tracked(
                b_argv(root, patterns), REPO_ROOT, temps=(root,), timeout=20,
                extra_env={"TZ": zone})
            bits = b_problems(
                proc, b_doc("all", REL_A, [], list(both_rows(mtime))), 0, root_text)
            if bits:
                problems.append(zone + " " + ",".join(bits))
            else:
                doc, _problem_line, _problem = stdout_docs(proc.stdout or "", 1)
                tz_docs.append(doc["files"][0]["mtime"] if isinstance(doc, dict) else None)
        if len(tz_docs) == 2 and tz_docs[0] != tz_docs[1]:
            problems.append("tz mtime differs")
        if tz_docs and (tz_docs[0] is None or not MTIME_RE.match(str(tz_docs[0]))):
            problems.append("mtime shape")
        bare = run_tracked(
            [sys.executable, B_REL, "--root", str(root), "--date", RUN_DATE],
            REPO_ROOT, temps=(root,), timeout=20)
        if bare.returncode != 2:
            problems.append("no pattern exit " + str(bare.returncode))
        if (bare.stdout or "").strip():
            problems.append("no pattern stdout")
        if not (bare.stderr or "").strip():
            problems.append("no pattern stderr empty")
        if root_text in (bare.stdout or ""):
            problems.append("no pattern leaked")
        if is_root():
            blocked_note = "mode 000 is not proof when running as root"
        else:
            try:
                for child in root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                plant(root, (REL_A,), MTIME_STAMP)
                locked = root / REL_A
                os.chmod(locked, 0)
                stuck = (locked.stat().st_mode & 0o777) == 0
            except OSError as exc:
                return BLOCKED, "chmod " + type(exc).__name__
            if not stuck:
                problems.append("chmod did not stick")
            else:
                try:
                    proc = run_tracked(
                        b_argv(root, patterns), REPO_ROOT, temps=(root,), timeout=20)
                    bits = b_problems(
                        proc,
                        b_doc("partial", REL_A, [REL_B], list(only_first_rows(mtime))),
                        0,
                        root_text,
                    )
                    if bits:
                        problems.append("mode000 " + ",".join(bits))
                finally:
                    try:
                        os.chmod(locked, 0o644)
                    except OSError:
                        pass
    if blocked_note:
        note_blocked("G6 mode 000", blocked_note)
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "cases=5 tz=same mode000=exists"


def g7_writes():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    if not TRACKED:
        return FAIL, "no G3-G6 executions"
    bad = []
    for index, problems in enumerate(TRACKED, 1):
        if problems:
            bad.append(str(index) + " " + ",".join(problems))
    if bad:
        return FAIL, join_bits(bad)
    return PASS, "runs=" + str(len(TRACKED))


def g8_tests():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    holder, status, detail = make_temp("check012-tests-")
    if holder is None:
        return status, detail
    wrapper = (
        "import io\n"
        "import socket\n"
        "import sys\n"
        "\n"
        "sys.dont_write_bytecode = True\n"
        "\n"
        "def _gate012_blocked(self, *args, **kwargs):\n"
        "    raise OSError('blocked')\n"
        "\n"
        "socket.socket.connect = _gate012_blocked\n"
        "import unittest\n"
        "program = unittest.main(\n"
        "    module=None,\n"
        "    argv=['unittest', 'discover', '-s', 'routines/tests'],\n"
        "    exit=False,\n"
        ")\n"
        "sys.exit(0 if program.result.wasSuccessful() else 1)\n"
    )
    with holder:
        path = Path(holder.name) / "offline_tests.py"
        try:
            compile(wrapper, "<g8>", "exec")
            path.write_text(wrapper, encoding="utf-8", newline="\n")
        except (OSError, SyntaxError) as exc:
            return FAIL, "wrapper " + type(exc).__name__
        proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=60)
    if proc.returncode == 127:
        return BLOCKED, "unittest could not start"
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    count = ran_count(text)
    ran = "none" if count is None else str(count)
    if proc.returncode != 0 or count is None or count < MIN_TESTS:
        return FAIL, "unittest_exit=" + str(proc.returncode) + " ran=" + ran
    return PASS, "unittest_exit=0 ran=" + ran


def mutant_label(name, proc):
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    count = ran_count(text)
    ran = "none" if count is None else str(count)
    red = proc.returncode not in (0, 127) and count is not None and count > 0
    label = name + " exit " + str(proc.returncode) + " ran=" + ran
    if red:
        return label + " red", True
    if proc.returncode == 0:
        return label + " still green", False
    return label + " not red", False


def g9_mutants():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    sources = {}
    for rel in SCRIPTS:
        tree, source, problem = load_tree(rel)
        if problem:
            return FAIL, problem
        sources[rel] = source
    live = run_process(unittest_argv(), REPO_ROOT, timeout=60)
    if live.returncode == 127:
        return BLOCKED, "live tests could not start"
    if live.returncode != 0:
        return FAIL, "tests are not green before mutation exit=" + str(live.returncode)
    holder, status, detail = make_temp("check012-mut-")
    if holder is None:
        return status, detail
    with holder:
        try:
            pack = Path(holder.name) / "repo"
            shutil.copytree(REPO_ROOT, pack, ignore=ignore_noise)
        except OSError as exc:
            return BLOCKED, "temp copy " + type(exc).__name__
        try:
            inside = pack.resolve().is_relative_to(REPO_ROOT.resolve())
        except OSError as exc:
            return BLOCKED, "temp copy " + type(exc).__name__
        if inside:
            return FAIL, "temp copy aliased the live tree"
        parts = []
        miss = False
        for name, rel, wrapper in MUTANTS:
            for script, source in sources.items():
                dest = pack / script
                try:
                    dest.write_text(source, encoding="utf-8", newline="\n")
                except OSError as exc:
                    return BLOCKED, "restore " + type(exc).__name__
            try:
                rewritten = append_mutant(sources[rel], wrapper)
            except (SyntaxError, ValueError) as exc:
                return FAIL, name + " could not be installed: " + type(exc).__name__
            dest = pack / rel
            try:
                if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
                    return FAIL, "mutant write landed in the live tree"
                dest.write_text(rewritten, encoding="utf-8", newline="\n")
            except OSError as exc:
                return BLOCKED, "mutant write " + type(exc).__name__
            proc = run_process(unittest_argv(), pack, timeout=60)
            if proc.returncode == 127:
                return BLOCKED, name + " could not start"
            label, red = mutant_label(name, proc)
            if not red:
                miss = True
            parts.append(label)
        if miss:
            return FAIL, "; ".join(parts)
        return PASS, "; ".join(parts)


def g10_hygiene():
    problems = []
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        problems.append("missing " + ", ".join(missing))
    else:
        problems.extend(hygiene_problems())
    for rel in ("tools/check_010.py", "tools/check_011.py"):
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(rel + " missing")
            continue
        proc = run_process(
            [sys.executable, str(path)], REPO_ROOT, timeout=180, pythonpath=None)
        if proc.returncode == 127:
            return BLOCKED, rel + " could not start"
        line = result_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
        if proc.returncode != 0 or not line.startswith("RESULT: ALL PASS"):
            problems.append(rel + " exit " + str(proc.returncode) + " " + one_line(line))
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "files=5 check_010=0 check_011=0"


def g11_pattern():
    # G11 checks structure only.
    if missing_rels((B_REL,)):
        return FAIL, "missing " + B_REL
    tree, _source, problem = load_tree(B_REL)
    if problem:
        return FAIL, problem
    problems = pattern_structure(tree)
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "pattern required=True default=absent"


def run_gate(title, func):
    try:
        status, detail = func()
    except Exception as exc:
        status, detail = FAIL, "internal " + type(exc).__name__ + ": " + str(exc)
    gate(title, status, detail)


def main():
    del FAILURES[:]
    del TRACKED[:]
    run_gate(
        "G1 five files exist; both scripts import with empty stdout and stderr; "
        "main is defined; imports stay in the stdlib",
        g1_shape,
    )
    run_gate(
        "G2 neither script writes, and script B does not read bodies or list directories",
        g2_static,
    )
    run_gate(
        "G3 changelog fixture cases match A6, including a 127.0.0.1 server fetch",
        g3_behavior,
    )
    run_gate(
        "G4 closed port, file URL, empty page, and bait page fail closed",
        g4_unreadable,
    )
    run_gate(
        "G5 --text-line for exit 0 and exit 10 matches A5",
        g5_text,
    )
    run_gate(
        "G6 daily file presence, TZ-independent mtime, and mode 000",
        g6_presence,
    )
    run_gate(
        "G7 repo and temp snapshots are unchanged around every G3-G6 run",
        g7_writes,
    )
    run_gate(
        "G8 unittest discover stays green offline and runs at least 16 tests",
        g8_tests,
    )
    run_gate(
        "G9 temp-copy mutants M1 M2 M3 each make the routine tests fail",
        g9_mutants,
    )
    run_gate(
        "G10 the five files match C4, and check_010.py and check_011.py exit 0",
        g10_hygiene,
    )
    run_gate(
        "G11 --pattern is required and has no default",
        g11_pattern,
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
