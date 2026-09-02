#!/usr/bin/env python3
"""check_003 - agy edits hello.py and adds a unittest.

Written before the work-order implementation.  G1, G2, and live G4 are
expected red until agy extracts greet(), adds tests/test_hello.py, and
leaves matching artifacts.  G4 also mutates greet() on a temp copy: if
that copy still passes unittest, the test is empty and G4 stays red.
001/002 are re-run as regression and must stay green.

Stdlib only, offline, ASCII stdout.  Does not touch check_001/002 or
their delivery files.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

GREETING = "Hello, Gitmy!"
MODEL = "gemini-3.7-flash-high"
HELLO_REL = "src/hello.py"
TEST_REL = "tests/test_hello.py"
SKIP_LINE = (
    "Print mode: --dangerously-skip-permissions set, "
    "auto-approving all tool permissions"
)
CONV = "33333333-3333-3333-3333-333333333333"

# src/hello.py as of 002 close (#6 / #7 parent).  A no-op delivery equals this.
BASELINE_HELLO = (
    "def main():\n"
    "    print(\"Hello, Gitmy! \U0001F44B\")\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    main()\n"
)

FAILURES = []
GATE_OUTCOMES = []


def ascii_text(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def one_line(value):
    return ascii_text(value).replace("\r", "\\r").replace("\n", "\\n")


def gate(name, ok, detail=""):
    GATE_OUTCOMES.append(bool(ok))
    if ok:
        print("[PASS] " + one_line(name))
    else:
        FAILURES.append(name)
        suffix = " -- " + one_line(detail) if detail else ""
        print("[FAIL] " + one_line(name) + suffix)


def write_utf8(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def slash_haystack(text):
    return (text or "").replace("\\", "/").replace("\r\n", "\n")


def load_json(path):
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("json root is not an object")
    return payload, raw


def child_env():
    env = dict(os.environ)
    for key in (
            "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
            "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_process(argv, cwd, timeout=60, extra_env=None):
    env = child_env()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, cwd=str(cwd), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            argv, 124, exc.stdout or "", (exc.stderr or "") + "\ntimeout")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def remnants_001_002(root):
    root = Path(root)
    needed = (
        root / "src" / "agy_wrote.txt",
        root / "src" / "agy_headless.txt",
        root / "artifacts" / "agy-001.json",
        root / "artifacts" / "agy-001.log",
        root / "artifacts" / "agy-002.json",
        root / "artifacts" / "agy-002.log",
        root / "tools" / "check_001.py",
        root / "tools" / "check_002.py",
    )
    missing = [str(p.relative_to(root)).replace("\\", "/")
               for p in needed if not p.is_file()]
    return not missing, missing


def load_hello_module(path):
    unique = "hello_mod_" + str(path.stat().st_mtime_ns)
    spec = importlib.util.spec_from_file_location(unique, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main_calls_greet(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Name) and func.id == "greet":
                        return True
    return False


def has_greet_fn(source):
    tree = ast.parse(source)
    return any(isinstance(n, ast.FunctionDef) and n.name == "greet"
               for n in tree.body)


def g1_shape_on_live_tree():
    root = REPO_ROOT
    hello = root / HELLO_REL
    testp = root / TEST_REL
    remnant_ok, missing = remnants_001_002(root)
    if not hello.is_file():
        return False, "src/hello.py missing"
    source = hello.read_text(encoding="utf-8")
    greeting_in_file = GREETING in source
    changed = source.replace("\r\n", "\n") != BASELINE_HELLO
    has_greet = False
    greet_ok = False
    calls = False
    try:
        has_greet = has_greet_fn(source)
        calls = main_calls_greet(source)
        if has_greet:
            mod = load_hello_module(hello)
            greet_ok = GREETING in str(mod.greet())
    except Exception as exc:
        greet_ok = False
        has_greet = has_greet or False
        detail_exc = type(exc).__name__ + ": " + str(exc)
    else:
        detail_exc = ""
    run = run_process([sys.executable, str(hello)], root, timeout=30)
    stdout_ok = GREETING in ((run.stdout or "") + (run.stderr or ""))
    test_exists = testp.is_file()
    test_has_unittest = False
    test_mentions_greet = False
    if test_exists:
        test_src = testp.read_text(encoding="utf-8")
        test_has_unittest = "unittest" in test_src
        test_mentions_greet = "greet" in test_src and GREETING in test_src
    ok = (greeting_in_file and changed and has_greet and greet_ok and calls
          and stdout_ok and test_exists and test_has_unittest
          and test_mentions_greet and remnant_ok)
    detail = (
        "greeting=" + str(greeting_in_file)
        + "; diff_from_002=" + str(changed)
        + "; greet_fn=" + str(has_greet)
        + "; greet_returns=" + str(greet_ok)
        + "; main_calls_greet=" + str(calls)
        + "; stdout_greeting=" + str(stdout_ok)
        + "; test_file=" + str(test_exists)
        + "; test_unittest=" + str(test_has_unittest)
        + "; test_asserts_greet=" + str(test_mentions_greet)
        + "; remnants=" + str(remnant_ok)
        + ("; missing=" + ",".join(missing) if missing else "")
        + ("; exc=" + detail_exc if detail_exc else "")
    )
    return ok, detail


def g2_artifacts_prove_edit(root=None):
    root = Path(REPO_ROOT if root is None else root)
    art_json = root / "artifacts" / "agy-003.json"
    art_log = root / "artifacts" / "agy-003.log"
    if not art_json.is_file() or not art_log.is_file():
        return False, "missing artifacts/agy-003.json or artifacts/agy-003.log"
    try:
        payload, json_raw = load_json(art_json)
    except Exception as exc:
        return False, "json: " + type(exc).__name__ + ": " + str(exc)
    log_text = art_log.read_text(encoding="utf-8", errors="replace")
    hay = slash_haystack(json_raw + "\n" + log_text)
    status = str(payload.get("status") or "")
    conv = str(payload.get("conversation_id") or "")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    try:
        tokens_ok = int(usage.get("input_tokens")) > 0
    except (TypeError, ValueError):
        tokens_ok = False
    status_ok = status.upper() == "SUCCESS"
    conv_ok = bool(re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        conv))
    model_in_log = (
        ('model="' + MODEL + '"') in log_text
        or ("Resolving model " + MODEL) in log_text
        or ("Model ID " + MODEL) in log_text
    )
    skip_ok = SKIP_LINE in log_text
    conv_in_log = bool(conv) and conv in log_text
    hello_ok = HELLO_REL in hay
    test_ok = TEST_REL in hay
    greeting_ok = GREETING in hay
    ok = (status_ok and conv_ok and tokens_ok and model_in_log and skip_ok
          and conv_in_log and hello_ok and test_ok and greeting_ok)
    detail = (
        "status=" + status
        + "; conv=" + str(conv_ok)
        + "; tokens_ok=" + str(tokens_ok)
        + "; model_in_log=" + str(model_in_log)
        + "; skip_line=" + str(skip_ok)
        + "; conv_in_log=" + str(conv_in_log)
        + "; hello_py=" + str(hello_ok)
        + "; test_hello=" + str(test_ok)
        + "; greeting_in_artifacts=" + str(greeting_ok)
    )
    return ok, detail


PROXY_JSON = json.dumps({
    "conversation_id": CONV,
    "status": "SUCCESS",
    "response": "PING_OK\n",
    "duration_seconds": 1.0,
    "num_turns": 1,
    "usage": {
        "input_tokens": 100,
        "output_tokens": 4,
        "thinking_tokens": 0,
        "cache_read_tokens": 0,
        "total_tokens": 104,
    },
}, indent=2) + "\n"

GOOD_LOG = (
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'printmode.go:173] Print mode: starting (promptLength=10, '
    'model="gemini-3.7-flash-high", conversationID="")\n'
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'session.go:65] ' + SKIP_LINE + '\n'
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'server.go:1142] Created conversation ' + CONV + '\n'
    + HELLO_REL + '\n'
    + GREETING + '\n'
    + TEST_REL + '\n'
)


def constructed_tree(parent, name):
    root = Path(parent) / name
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    write_utf8(root / HELLO_REL,
               "def greet():\n    return \"" + GREETING + "\"\n"
               "def main():\n    print(greet())\n")
    write_utf8(root / TEST_REL, "import unittest\n")
    return root


def g3_proxy_edit_turns_g2_red(work):
    missing = constructed_tree(work, "file-only")
    stripped = constructed_tree(work, "stripped-write")
    write_utf8(stripped / "artifacts" / "agy-003.json", PROXY_JSON)
    write_utf8(
        stripped / "artifacts" / "agy-003.log",
        GOOD_LOG.replace(HELLO_REL + "\n", "").replace(TEST_REL + "\n", ""),
    )
    a_ok, a_detail = g2_artifacts_prove_edit(missing)
    b_ok, b_detail = g2_artifacts_prove_edit(stripped)
    ok = (not a_ok) and (not b_ok)
    detail = (
        "file-only must be red: " + a_detail
        + " ;; stripped-write must be red: " + b_detail
    )
    return ok, detail


def break_greet(source):
    tree = ast.parse(source)
    found = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "greet":
            node.body = [ast.Return(value=ast.Constant(value="broken"))]
            found = True
    if not found:
        raise ValueError("greet() not found")
    return ast.unparse(tree) + "\n"


def run_unittest(root):
    return run_process(
        [sys.executable, "-m", "unittest", "tests.test_hello"],
        root, timeout=60,
        extra_env={"PYTHONPATH": str(root) + os.pathsep + str(root / "src")})


def g4_unittest_has_teeth(work):
    live = run_unittest(REPO_ROOT)
    live_ok = live.returncode == 0
    hello = REPO_ROOT / HELLO_REL
    testp = REPO_ROOT / TEST_REL
    if not hello.is_file() or not testp.is_file():
        return False, (
            "live unittest exit=" + str(live.returncode)
            + "; missing hello or test file for mutation"
        )
    pack = Path(work) / "g4"
    (pack / "src").mkdir(parents=True, exist_ok=True)
    (pack / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(hello), str(pack / HELLO_REL))
    shutil.copy2(str(testp), str(pack / TEST_REL))
    write_utf8(pack / "tests" / "__init__.py", "")
    try:
        broken_src = break_greet((pack / HELLO_REL).read_text(encoding="utf-8"))
    except Exception as exc:
        return False, (
            "live unittest exit=" + str(live.returncode)
            + "; mutate=" + type(exc).__name__ + ": " + str(exc)
        )
    write_utf8(pack / HELLO_REL, broken_src)
    broken = run_unittest(pack)
    broken_red = broken.returncode != 0
    ok = live_ok and broken_red
    detail = (
        "live_exit=" + str(live.returncode)
        + "; broken_exit=" + str(broken.returncode)
        + "; broken_must_be_red=" + str(broken_red)
        + "; live_tail=" + repr(((live.stdout or "") + (live.stderr or "")).strip()[-180:])
        + "; broken_tail=" + repr(((broken.stdout or "") + (broken.stderr or "")).strip()[-180:])
    )
    return ok, detail


def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def run_regression(name, path):
    if not path.is_file():
        gate("python " + name + " (regression)", False, "not found")
        return
    proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=60)
    out = (proc.stdout or "") + (proc.stderr or "")
    gate("python " + name + " (regression)",
         proc.returncode == 0 and result_line(out) == "RESULT: ALL PASS",
         "exit=" + str(proc.returncode) + "; " + repr(result_line(out)))


def main():
    g1_ok, g1_detail = g1_shape_on_live_tree()
    gate("G1 hello.py has greet(); test exists; 001/002 remnants stay",
         g1_ok, g1_detail)

    g2_ok, g2_detail = g2_artifacts_prove_edit()
    gate("G2 skip-permissions log and same run edited hello.py plus test",
         g2_ok, g2_detail)

    with tempfile.TemporaryDirectory(prefix="check003-") as tmp:
        g3_ok, g3_detail = g3_proxy_edit_turns_g2_red(tmp)
        gate("G3 file without a matching agy write record turns G2 red",
             g3_ok, g3_detail)

        g4_ok, g4_detail = g4_unittest_has_teeth(tmp)
        gate("G4 unittest is green and breaking greet() turns it red",
             g4_ok, g4_detail)

    run_regression("tools/check_001.py", REPO_ROOT / "tools" / "check_001.py")
    run_regression("tools/check_002.py", REPO_ROOT / "tools" / "check_002.py")

    print("")
    if FAILURES:
        print("RESULT: FAILED (" + str(len(FAILURES)) + " gate(s)): "
              + "; ".join(one_line(name) for name in FAILURES))
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
