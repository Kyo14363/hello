#!/usr/bin/env python3
"""check_007 - join_names turns a sequence of names into one English phrase.

Written before the work-order implementation. G1-G4 are expected red
until src/names.py and tests/test_names.py exist. G5 re-runs check_006
on this same tree and must stay green.

Stdlib only, offline, ASCII stdout. The live tree is read only: G4
rewrites join_names on a temp copy of the repo. Every child process
gets PYTHONIOENCODING=utf-8 and PYTHONDONTWRITEBYTECODE=1, has leaky
variables such as PYTHONPATH removed, then PYTHONPATH set to src.

Each check prints [PASS], [FAIL], or [BLOCKED]. The process exits 1
if any of them is not PASS. BLOCKED means the check could not be
executed (the interpreter did not start, or the temp copy could not
be made). A product miss is FAIL, including a missing src/names.py.
"""

import os
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

NAMES_REL = "src/names.py"
TEST_REL = "tests/test_names.py"
TEST_MODULE = "tests.test_names"
MIN_TESTS = 4

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)

# G5 hashes every file except these directories. The work order names
# both of them and does not exclude loose bytecode.
HASH_SKIP = {".git", "__pycache__"}
COPY_SKIP = {".git", "__pycache__", ".venv", "venv"}

# Network modules named by the work order, plus the same kind of client,
# server, and third-party HTTP library ("等").
NETWORK_MODULES = frozenset({
    "aiohttp",
    "asynchat",
    "asyncore",
    "ftplib",
    "http",
    "httplib",
    "httpx",
    "imaplib",
    "nntplib",
    "poplib",
    "requests",
    "smtpd",
    "smtplib",
    "socket",
    "socketserver",
    "ssl",
    "telnetlib",
    "urllib",
    "urllib2",
    "urllib3",
    "webbrowser",
    "wsgiref",
    "xmlrpc",
    "xmlrpclib",
})

STDLIB_MODULES = frozenset(sys.builtin_module_names) | frozenset(
    getattr(sys, "stdlib_module_names", ())
)

# R1 tables, in order. "ret" rows compare with == and require str.
# "exc" rows require the builtin TypeError.
CASES = (
    ("ret", [], ""),
    ("ret", ["Kyo"], "Kyo"),
    ("ret", ["Kyo", "Gitmy"], "Kyo and Gitmy"),
    ("ret", ("Kyo", "Gitmy"), "Kyo and Gitmy"),
    ("ret", ["Kyo", "Gitmy", "Ami"], "Kyo, Gitmy and Ami"),
    ("ret", ["A", "B", "C", "D"], "A, B, C and D"),
    ("ret", ["  Kyo ", "", "   ", "Gitmy"], "Kyo and Gitmy"),
    ("ret", ["", " "], ""),
    ("ret", ["Kyo", "Kyo"], "Kyo and Kyo"),
    ("exc", "Kyo", "TypeError"),
    ("exc", b"Kyo", "TypeError"),
    ("exc", ["Kyo", 3], "TypeError"),
    ("exc", ["Kyo", None], "TypeError"),
)

# M1: three or more names use an Oxford comma ("A, B, and C").
M1_SRC = """\
def join_names(names):
    if isinstance(names, (str, bytes)):
        raise TypeError("names must be an iterable of str")
    parts = []
    for item in names:
        if not isinstance(item, str):
            raise TypeError("each name must be str")
        text = item.strip()
        if text:
            parts.append(text)
    count = len(parts)
    if count == 0:
        return ""
    if count == 1:
        return parts[0]
    if count == 2:
        return parts[0] + " and " + parts[1]
    return ", ".join(parts[:-1]) + ", and " + parts[-1]
"""

# M2: do not strip and do not drop empty strings.
M2_SRC = """\
def join_names(names):
    if isinstance(names, (str, bytes)):
        raise TypeError("names must be an iterable of str")
    parts = []
    for item in names:
        if not isinstance(item, str):
            raise TypeError("each name must be str")
        parts.append(item)
    count = len(parts)
    if count == 0:
        return ""
    if count == 1:
        return parts[0]
    if count == 2:
        return parts[0] + " and " + parts[1]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
"""

# M3: a str is a sequence of characters and does not raise.
M3_SRC = """\
def join_names(names):
    if isinstance(names, bytes):
        raise TypeError("names must be an iterable of str")
    parts = []
    for item in names:
        if not isinstance(item, str):
            raise TypeError("each name must be str")
        text = item.strip()
        if text:
            parts.append(text)
    count = len(parts)
    if count == 0:
        return ""
    if count == 1:
        return parts[0]
    if count == 2:
        return parts[0] + " and " + parts[1]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
"""

MUTANTS = (
    ("M1", M1_SRC),
    ("M2", M2_SRC),
    ("M3", M3_SRC),
)

BEHAVIOR_DRIVER = """\
def run_case(value):
    before = list(value) if isinstance(value, list) else None
    try:
        got = names.join_names(value)
    except Exception as exc:
        mutated = before is not None and value != before
        return {
            "exc": type(exc).__name__,
            "exact_typeerror": type(exc) is TypeError,
            "mutated": mutated,
        }
    mutated = before is not None and value != before
    return {
        "exc": None,
        "exact_typeerror": False,
        "mutated": mutated,
        "is_str": isinstance(got, str),
        "value": got if isinstance(got, str) else repr(got),
    }

results = []
for value in cases:
    results.append(run_case(value))
probe = ["  Kyo ", "", "   ", "Gitmy"]
probe_before = list(probe)
try:
    names.join_names(probe)
except Exception:
    pass
print(json.dumps(
    {"probe_mutated": probe != probe_before, "results": results},
    ensure_ascii=True,
))
"""

RAN_RE = re.compile(r"^Ran (\d+) tests?\b", re.MULTILINE)

FAILURES = []


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
    """Environment for one child.

    Leaky variables, including PYTHONPATH, are removed. PYTHONPATH is
    then set to the literal src so imports follow the child's cwd.
    """
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "src"
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def run_process(argv, cwd, timeout=60, extra_env=None, input_text=None):
    kwargs = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(extra_env),
        cwd=str(cwd),
        timeout=timeout,
    )
    if input_text is not None:
        kwargs["input"] = input_text
    try:
        return subprocess.run(list(argv), **kwargs)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            argv, 124, exc.stdout or "", (exc.stderr or "") + "\ntimeout")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def tail(proc, n=160):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text[-n:]


def could_not_start(proc):
    return proc.returncode in (124, 127)


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def missing_product_files():
    missing = []
    if not (REPO_ROOT / NAMES_REL).is_file():
        missing.append(NAMES_REL)
    if not (REPO_ROOT / TEST_REL).is_file():
        missing.append(TEST_REL)
    return missing


def ran_count(text):
    found = RAN_RE.findall(text or "")
    if not found:
        return None
    return int(found[-1])


def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def run_unittest(root):
    return run_process(
        [sys.executable, "-m", "unittest", TEST_MODULE],
        root,
        timeout=60,
    )


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
    return [name for name in names
            if name in COPY_SKIP or name.endswith(".pyc")]


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


# ---------------------------------------------------------------- G1
def iter_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, False
        elif isinstance(node, ast.ImportFrom):
            relative = bool(node.level)
            if node.module:
                yield node.module, relative
            elif relative:
                for alias in node.names:
                    yield alias.name, True


def import_issue(module, relative):
    name = module or ""
    top = name.split(".", 1)[0] if name else ""
    if top == "hello":
        return "imports hello"
    if relative:
        return "relative import " + (name or ".")
    if top in NETWORK_MODULES:
        return "network module " + top
    if top not in STDLIB_MODULES:
        if not STDLIB_MODULES:
            return "stdlib list unavailable"
        return "not stdlib " + (top or name or "?")
    return None


def import_problems(tree):
    problems = []
    seen = set()
    for module, relative in iter_imports(tree):
        issue = import_issue(module, relative)
        if issue and issue not in seen:
            seen.add(issue)
            problems.append(issue)
    return problems


def signature_problems(tree):
    fns = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "join_names"
    ]
    if len(fns) != 1:
        return ["top-level join_names count " + str(len(fns))]
    args = fns[0].args
    problems = []
    positional = list(args.posonlyargs) + list(args.args)
    if len(positional) != 1:
        problems.append("positional parameters " + str(len(positional)))
    has_default = bool(args.defaults) or any(
        item is not None for item in args.kw_defaults
    )
    if has_default:
        problems.append("has a default")
    if args.vararg is not None:
        problems.append("has *args")
    if args.kwarg is not None:
        problems.append("has **kwargs")
    return problems


def g1_shape():
    missing = missing_product_files()
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    path = REPO_ROOT / NAMES_REL
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError as exc:
        return FAIL, "src/names.py does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return FAIL, "src/names.py unreadable: " + type(exc).__name__ + ": " + str(exc)
    problems = []
    problems.extend(signature_problems(tree))
    problems.extend(import_problems(tree))
    proc = run_process(
        [sys.executable, "-c", "import names"], REPO_ROOT, timeout=30)
    if could_not_start(proc):
        note = "import names could not start rc=" + str(proc.returncode)
        if problems:
            return FAIL, "; ".join(problems) + "; " + note
        return BLOCKED, note + " tail=" + one_line(tail(proc))
    noisy = (proc.stdout or "") != ""
    if proc.returncode != 0:
        problems.append("import names exit " + str(proc.returncode))
    if noisy:
        problems.append("import names stdout not empty")
    if problems:
        detail = "; ".join(problems)
        if proc.returncode != 0 or noisy:
            detail += " tail=" + one_line(tail(proc))
        return FAIL, detail
    return PASS, "import_stdout_empty=True"


# ---------------------------------------------------------------- G2
def behavior_source():
    lines = ["import json", "import names", "cases = ["]
    for _kind, value, _expected in CASES:
        lines.append("    " + repr(value) + ",")
    lines.append("]")
    lines.append(BEHAVIOR_DRIVER)
    return "\n".join(lines) + "\n"


def parse_probe_stdout(text):
    body = text[:-1] if text.endswith("\n") else text
    if body.endswith("\r"):
        body = body[:-1]
    if body == "" or "\n" in body or "\r" in body:
        return None, "behavior probe stdout is not one JSON line"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, "behavior probe stdout is not JSON"
    if not isinstance(payload, dict):
        return None, "behavior probe JSON is not an object"
    return payload, ""


def case_problem(kind, expected, got):
    if not isinstance(got, dict):
        return "result is not an object"
    problems = []
    if got.get("mutated"):
        problems.append("mutated the list")
    if kind == "ret":
        if got.get("exc") is not None:
            problems.append("raised " + str(got.get("exc")))
        elif not got.get("is_str"):
            problems.append("returned " + repr(got.get("value")))
        elif got.get("value") != expected:
            problems.append("value " + repr(got.get("value")))
    elif not got.get("exact_typeerror"):
        problems.append("exc " + repr(got.get("exc")))
    return ", ".join(problems)


def g2_behavior():
    if not (REPO_ROOT / NAMES_REL).is_file():
        return FAIL, "missing " + NAMES_REL
    script = behavior_source()
    try:
        compile(script, "<g2-probe>", "exec")
    except SyntaxError as exc:
        return FAIL, "behavior probe does not compile: " + str(exc)
    proc = run_process(
        [sys.executable, "-"], REPO_ROOT, timeout=30, input_text=script)
    if could_not_start(proc):
        return BLOCKED, "behavior probe could not start rc=" + str(proc.returncode)
    if proc.returncode != 0:
        return FAIL, (
            "behavior probe exit " + str(proc.returncode)
            + " tail=" + one_line(tail(proc))
        )
    payload, problem = parse_probe_stdout(proc.stdout or "")
    if problem:
        return FAIL, problem
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(CASES):
        got_len = len(results) if isinstance(results, list) else "none"
        return FAIL, "behavior probe result count " + str(got_len)
    mismatches = []
    for (kind, value, expected), got in zip(CASES, results):
        problem = case_problem(kind, expected, got)
        if problem:
            mismatches.append("input " + repr(value) + " " + problem)
    if payload.get("probe_mutated") is not False:
        mismatches.append("probe list changed")
    if mismatches:
        return FAIL, "; ".join(mismatches)
    return PASS, "rows=" + str(len(CASES)) + " list_unchanged=True"


# ---------------------------------------------------------------- G3
def g3_tests():
    missing = missing_product_files()
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    proc = run_unittest(REPO_ROOT)
    if could_not_start(proc):
        return BLOCKED, "unittest could not start rc=" + str(proc.returncode)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    count = ran_count(text)
    ran = "none" if count is None else str(count)
    detail = "unittest_exit=" + str(proc.returncode) + " ran=" + ran
    if proc.returncode != 0 or count is None or count < MIN_TESTS:
        return FAIL, detail + " tail=" + one_line(tail(proc))
    return PASS, detail


# ---------------------------------------------------------------- G4
def is_simple_rebind(node):
    if isinstance(node, ast.Assign):
        return (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "join_names"
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == "join_names"
    return False


def install_mutant(source, mutant_src):
    """Replace top-level join_names with the mutant. None if it is absent."""
    tree = ast.parse(source)
    parsed = ast.parse(mutant_src)
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.FunctionDef):
        raise ValueError("mutant source is not one function")
    mutant_fn = parsed.body[0]
    if mutant_fn.name != "join_names":
        raise ValueError("mutant function is not join_names")
    replaced = False
    new_body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "join_names":
            if not replaced:
                new_body.append(mutant_fn)
                replaced = True
            continue
        if is_simple_rebind(node):
            continue
        new_body.append(node)
    if not replaced:
        return None
    tree.body = new_body
    ast.fix_missing_locations(tree)
    rewritten = ast.unparse(tree)
    if not rewritten.endswith("\n"):
        rewritten += "\n"
    compile(rewritten, "<g4-mutant>", "exec")
    return rewritten


def mutant_label(name, proc):
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    count = ran_count(text)
    ran = "none" if count is None else str(count)
    red = proc.returncode != 0 and count is not None and count > 0
    label = name + " exit " + str(proc.returncode) + " ran=" + ran
    if red:
        return label + " red", True
    if proc.returncode == 0:
        return label + " still green", False
    return label + " not red tail=" + one_line(tail(proc)), False


def g4_in_copy(parent, source):
    pack = Path(parent) / "repo"
    try:
        shutil.copytree(REPO_ROOT, pack, ignore=ignore_noise)
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__ + ": " + str(exc)
    dest = pack / NAMES_REL
    root = REPO_ROOT.resolve()
    try:
        aliased = dest.resolve().is_relative_to(root)
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__ + ": " + str(exc)
    if aliased:
        return FAIL, "temp copy aliased the live tree"
    parts = []
    miss = False
    blocked = False
    for name, mutant_src in MUTANTS:
        try:
            rewritten = install_mutant(source, mutant_src)
        except (SyntaxError, ValueError) as exc:
            return FAIL, name + " could not be installed: " + type(exc).__name__ + ": " + str(exc)
        if rewritten is None:
            return FAIL, name + " could not be installed; top-level join_names missing"
        try:
            if dest.resolve().is_relative_to(root):
                return FAIL, "temp copy aliased the live tree"
            dest.write_text(rewritten, encoding="utf-8", newline="\n")
            if dest.resolve().is_relative_to(root):
                return FAIL, "mutant write landed in the live tree"
        except OSError as exc:
            return BLOCKED, "mutant write failed: " + type(exc).__name__ + ": " + str(exc)
        proc = run_unittest(pack)
        if could_not_start(proc):
            blocked = True
            parts.append(name + " could not start rc=" + str(proc.returncode))
            continue
        label, red = mutant_label(name, proc)
        if not red:
            miss = True
        parts.append(label)
    if miss:
        return FAIL, "; ".join(parts)
    if blocked:
        return BLOCKED, "; ".join(parts)
    return PASS, "; ".join(parts)


def g4_mutants():
    missing = missing_product_files()
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    path = REPO_ROOT / NAMES_REL
    try:
        source = read_text(path)
        ast.parse(source)
    except SyntaxError as exc:
        return FAIL, "src/names.py does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return FAIL, "src/names.py unreadable: " + type(exc).__name__ + ": " + str(exc)
    live = run_unittest(REPO_ROOT)
    if could_not_start(live):
        return BLOCKED, "live tests could not start rc=" + str(live.returncode)
    if live.returncode != 0:
        return FAIL, (
            "tests are not green before mutation"
            + " exit=" + str(live.returncode)
            + " tail=" + one_line(tail(live))
        )
    parent = outside_temp_parent()
    if parent is None:
        return BLOCKED, "temp copy failed: no directory outside the repo"
    try:
        tmp = tempfile.TemporaryDirectory(prefix="check007-", dir=str(parent))
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__ + ": " + str(exc)
    with tmp:
        return g4_in_copy(tmp.name, source)


# ---------------------------------------------------------------- G5
def g5_regression(before):
    path = REPO_ROOT / "tools" / "check_006.py"
    if not path.is_file():
        changed = blob_changes(before, live_blobs())
        detail = "tools/check_006.py missing"
        if changed:
            detail += "; live blobs changed: " + ",".join(changed)
        return FAIL, detail
    proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=120)
    changed = blob_changes(before, live_blobs())
    change_note = ""
    if changed:
        change_note = "; live blobs changed: " + ",".join(changed)
    if could_not_start(proc):
        note = "check_006 could not start rc=" + str(proc.returncode)
        if changed:
            return FAIL, note + change_note
        return BLOCKED, note
    line = result_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
    detail = "check_006 exit " + str(proc.returncode) + " " + repr(line) + change_note
    if proc.returncode == 0 and not changed:
        return PASS, detail
    return FAIL, detail


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
        "G1 src/names.py and tests/test_names.py exist; "
        "join_names has one positional parameter, no default, no *args or **kwargs; "
        "imports are stdlib and not network; import names stdout is empty",
        g1_shape,
    )
    run_gate(
        "G2 join_names matches the R1 tables and does not mutate the caller's list",
        g2_behavior,
    )
    run_gate(
        "G3 unittest tests.test_names exits 0 and runs at least 4 tests",
        g3_tests,
    )
    run_gate(
        "G4 temp-copy mutants M1 M2 M3 each make tests.test_names fail",
        g4_mutants,
    )
    run_gate(
        "G5 check_006.py exits 0 and live file hashes are unchanged",
        lambda: g5_regression(before),
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
