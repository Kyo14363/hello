#!/usr/bin/env python3
"""check_004 - a Cursor cloud agent adds farewell(name) and a test.

Written before the work-order implementation (spec R4).  G1-G3 are
expected red on a main that has no farewell(); G4 re-runs 001-003 as
regression and must stay green.

Stdlib only, offline, ASCII stdout.  The live tree is read only: the
farewell mutation in G3 happens on a temp copy, and child processes run
with PYTHONDONTWRITEBYTECODE so no __pycache__ lands in the repo.
unittest runs with PYTHONPATH=<root>:<root>/src, the same convention
check_003 uses, because tests/test_hello.py does `from hello import ...`.
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

GREETING = "Hello, Gitmy!"
HELLO_REL = "src/hello.py"
TEST_REL = "tests/test_hello.py"
NAMES = ("Gitmy", "Kyo")

DELIVERABLES_001_003 = (
    "src/agy_wrote.txt",
    "src/agy_headless.txt",
    "artifacts/agy-001.json",
    "artifacts/agy-001.log",
    "artifacts/agy-002.json",
    "artifacts/agy-002.log",
    "artifacts/agy-003.json",
    "artifacts/agy-003.log",
    "tools/check_001.py",
    "tools/check_002.py",
    "tools/check_003.py",
    TEST_REL,
)

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)

FAILURES = []


def ascii_text(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def one_line(value):
    return ascii_text(value).replace("\r", "\\r").replace("\n", "\\n")


def gate(name, ok, detail=""):
    if ok:
        print("[PASS] " + one_line(name))
    else:
        FAILURES.append(name)
        suffix = " -- " + one_line(detail) if detail else ""
        print("[FAIL] " + one_line(name) + suffix)


def child_env(extra=None):
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def run_process(argv, cwd, timeout=60, extra_env=None):
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=child_env(extra_env), cwd=str(cwd),
            timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            argv, 124, exc.stdout or "", (exc.stderr or "") + "\ntimeout")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def tail(proc, n=180):
    return repr(((proc.stdout or "") + (proc.stderr or "")).strip()[-n:])


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def top_functions(source):
    tree = ast.parse(source)
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def fn_prints(node):
    for child in ast.walk(node):
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id == "print"):
            return True
    return False


def fn_returns_value(node):
    return any(isinstance(c, ast.Return) and c.value is not None
               for c in ast.walk(node))


def src_path_env(root):
    root = Path(root)
    return {"PYTHONPATH": str(root) + os.pathsep + str(root / "src")}


# ---------------------------------------------------------------- G1
def g1_shape():
    hello = REPO_ROOT / HELLO_REL
    missing = [rel for rel in DELIVERABLES_001_003
               if not (REPO_ROOT / rel).is_file()]
    if not hello.is_file():
        return False, "src/hello.py missing"
    source = read_text(hello)
    try:
        fns = top_functions(source)
    except SyntaxError as exc:
        return False, "hello.py does not parse: " + str(exc)
    greet = fns.get("greet")
    fare = fns.get("farewell")
    greet_ok = greet is not None and not greet.args.args
    fare_args = [a.arg for a in fare.args.args] if fare is not None else []
    fare_sig_ok = fare is not None and len(fare_args) == 1
    fare_style_ok = (fare is not None and fn_returns_value(fare)
                     and not fn_prints(fare))
    greeting_ok = GREETING in source
    ok = (greet_ok and fare_sig_ok and fare_style_ok and greeting_ok
          and not missing)
    detail = (
        "greet()=" + str(greet_ok)
        + "; farewell(name)=" + str(fare_sig_ok)
        + "; farewell_args=" + str(fare_args)
        + "; farewell_returns_not_prints=" + str(fare_style_ok)
        + "; greeting_literal=" + str(greeting_ok)
        + ("; missing=" + ",".join(missing) if missing else "")
    )
    return ok, detail


# ---------------------------------------------------------------- G2
PROBE = r'''
import importlib.util, json, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("hello_probe", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = {"greet": str(mod.greet())}
for name in sys.argv[2:]:
    out["farewell:" + name] = str(mod.farewell(name))
sys.stdout.write(json.dumps(out, ensure_ascii=True))
'''


def g2_behavior():
    import json
    hello = REPO_ROOT / HELLO_REL
    if not hello.is_file():
        return False, "src/hello.py missing"
    probe = run_process(
        [sys.executable, "-c", PROBE, str(hello)] + list(NAMES),
        REPO_ROOT, timeout=30)
    try:
        got = json.loads(probe.stdout or "")
    except ValueError:
        return False, "probe exit=" + str(probe.returncode) + "; " + tail(probe)
    checks = []
    for name in NAMES:
        want = "Goodbye, " + name + "!"
        checks.append((name, want in got.get("farewell:" + name, "")))
    greet_ok = GREETING in got.get("greet", "")
    run = run_process([sys.executable, str(hello)], REPO_ROOT, timeout=30)
    stdout_ok = run.returncode == 0 and GREETING in (run.stdout or "")
    ok = all(c for _, c in checks) and greet_ok and stdout_ok
    detail = (
        "; ".join("farewell(" + n + ")=" + str(c) for n, c in checks)
        + "; greet=" + str(greet_ok)
        + "; script_stdout=" + str(stdout_ok)
        + "; got=" + one_line(json.dumps(got, ensure_ascii=True))
    )
    return ok, detail


# ---------------------------------------------------------------- G3
def farewell_tests(test_source):
    """Names of test methods that call farewell() and mention Goodbye."""
    tree = ast.parse(test_source)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name.startswith("test")):
            continue
        calls = any(
            isinstance(c, ast.Call) and (
                (isinstance(c.func, ast.Name) and c.func.id == "farewell")
                or (isinstance(c.func, ast.Attribute)
                    and c.func.attr == "farewell"))
            for c in ast.walk(node))
        asserts = any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr.startswith("assert")
            for c in ast.walk(node))
        goodbye = "Goodbye, " in ast.get_source_segment(test_source, node) \
            if hasattr(ast, "get_source_segment") else False
        if calls and asserts and goodbye:
            found.append(node.name)
    return found


def break_farewell(source):
    tree = ast.parse(source)
    hit = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "farewell":
            node.body = [ast.Return(value=ast.Constant(value=""))]
            hit = True
    if not hit:
        raise ValueError("farewell() not found")
    return ast.unparse(tree) + "\n"


def run_unittest(root):
    return run_process(
        [sys.executable, "-m", "unittest", "-v", "tests.test_hello"],
        root, timeout=60, extra_env=src_path_env(root))


def g3_test_has_teeth(work):
    hello = REPO_ROOT / HELLO_REL
    testp = REPO_ROOT / TEST_REL
    if not hello.is_file() or not testp.is_file():
        return False, "missing src/hello.py or tests/test_hello.py"
    test_src = read_text(testp)
    try:
        names = farewell_tests(test_src)
    except SyntaxError as exc:
        return False, "test does not parse: " + str(exc)
    imports_unittest = "import unittest" in test_src
    no_pytest = "pytest" not in test_src
    live = run_unittest(REPO_ROOT)
    live_ok = live.returncode == 0
    pack = Path(work) / "g3"
    (pack / "src").mkdir(parents=True, exist_ok=True)
    (pack / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(hello), str(pack / HELLO_REL))
    shutil.copy2(str(testp), str(pack / TEST_REL))
    try:
        broken = break_farewell(read_text(pack / HELLO_REL))
    except Exception as exc:
        return False, ("live_exit=" + str(live.returncode) + "; mutate="
                       + type(exc).__name__ + ": " + str(exc))
    (pack / HELLO_REL).write_text(broken, encoding="utf-8", newline="\n")
    mutant = run_unittest(pack)
    mutant_out = (mutant.stdout or "") + (mutant.stderr or "")
    red_names = [n for n in names
                 if ("FAIL: " + n) in mutant_out or ("ERROR: " + n) in mutant_out]
    ok = (bool(names) and imports_unittest and no_pytest and live_ok
          and mutant.returncode != 0 and bool(red_names))
    detail = (
        "farewell_tests=" + str(names)
        + "; unittest_import=" + str(imports_unittest)
        + "; no_pytest=" + str(no_pytest)
        + "; live_exit=" + str(live.returncode)
        + "; mutant_exit=" + str(mutant.returncode)
        + "; red_after_mutation=" + str(red_names)
        + "; live_tail=" + tail(live)
        + "; mutant_tail=" + tail(mutant)
    )
    return ok, detail


# ---------------------------------------------------------------- G4
def result_line(text):
    lines = [l for l in text.splitlines() if l.startswith("RESULT:")]
    return lines[-1] if lines else ""


def g4_regression():
    parts = []
    ok = True
    for name in ("check_001.py", "check_002.py", "check_003.py"):
        path = REPO_ROOT / "tools" / name
        if not path.is_file():
            ok = False
            parts.append(name + "=missing")
            continue
        proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=120)
        line = result_line((proc.stdout or "") + (proc.stderr or ""))
        this_ok = proc.returncode == 0 and line == "RESULT: ALL PASS"
        ok = ok and this_ok
        parts.append(name + "=exit " + str(proc.returncode) + " " + repr(line))
    return ok, "; ".join(parts)


def main():
    g1_ok, g1_detail = g1_shape()
    gate("G1 hello.py has greet() and farewell(name); greeting and 001-003 "
         "deliverables stay", g1_ok, g1_detail)

    g2_ok, g2_detail = g2_behavior()
    gate("G2 farewell(Gitmy)/farewell(Kyo) say Goodbye; greet() and "
         "script output unchanged", g2_ok, g2_detail)

    with tempfile.TemporaryDirectory(prefix="check004-") as tmp:
        g3_ok, g3_detail = g3_test_has_teeth(tmp)
    gate("G3 unittest is green and breaking farewell() on a temp copy "
         "turns a farewell test red", g3_ok, g3_detail)

    g4_ok, g4_detail = g4_regression()
    gate("G4 check_001, check_002, check_003 still ALL PASS", g4_ok, g4_detail)

    print("")
    if FAILURES:
        print("RESULT: FAIL (" + str(len(FAILURES)) + " gate(s)): "
              + "; ".join(one_line(n) for n in FAILURES))
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
