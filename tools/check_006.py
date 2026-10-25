#!/usr/bin/env python3
"""check_006 - hello.py takes one name on argv.

Written before the work-order implementation. G1-G3 are expected red
until the with-name path exists and a test depends on it. G4 re-runs
check_003 and check_004 on this same tree and must stay green.

Stdlib only, offline, ASCII stdout. The live tree is read only: G3
rewrites the with-name path on a temp copy of the repo. Every child
process gets PYTHONIOENCODING=utf-8 and does not write bytecode.

Each check prints [PASS], [FAIL], or [BLOCKED]. All four are block-level:
the process exits 1 if any of them is not PASS. BLOCKED means the check
could not be executed (the interpreter did not start, or the temp copy
could not be made). A product miss is FAIL, including a with-name path
that cannot be located.
"""

import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

HELLO_REL = "src/hello.py"
TEST_REL = "tests/test_hello.py"
TEST_MODULE = "tests.test_hello"
NAMED = "Kyo"
GREETING = "Hello, Gitmy!"
NAMED_GREETING = "Hello, " + NAMED + "!"
HELLO_PREFIX = "Hello, "

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)

SKIP_WALK = {".git", "__pycache__", ".venv", "venv"}
RUNNERS = {
    "run", "check_output", "check_call", "Popen", "call", "system",
    "run_path", "run_module",
}

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
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
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


def tail(proc, n=160):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text[-n:]


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def src_path_env(root):
    root = Path(root)
    return {"PYTHONPATH": str(root) + os.pathsep + str(root / "src")}


def could_not_start(proc):
    return proc.returncode in (124, 127)


def call_func_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def contains_const(node, needle):
    if node is None:
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if needle in child.value.replace("\\", "/"):
                return True
    return False


def is_function(node):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def top_functions(tree):
    return [node for node in tree.body if is_function(node)]


# ---------------------------------------------------------------- path
def static_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return static_string(node.left) and static_string(node.right)
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(value, ast.Constant) for value in node.values)
    return False


def dynamic_hello(node):
    for child in ast.walk(node):
        if isinstance(child, ast.JoinedStr):
            consts = []
            dynamic = False
            for value in child.values:
                if isinstance(value, ast.FormattedValue):
                    dynamic = True
                elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                    consts.append(value.value)
            if dynamic and any(HELLO_PREFIX in item for item in consts):
                return True
        if isinstance(child, ast.BinOp) and isinstance(child.op, (ast.Add, ast.Mod)):
            if contains_const(child, HELLO_PREFIX) and not static_string(child):
                return True
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == "format"
                and contains_const(child.func.value, HELLO_PREFIX)
                and (child.args or child.keywords)):
            return True
    return False


def is_name_aware(node):
    """True when a function or __main__ guard can see a caller-supplied name."""
    if is_function(node):
        args = node.args
        if (args.args or args.posonlyargs or args.vararg or args.kwonlyargs
                or args.kwarg):
            return True
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == "argv":
            return True
        if isinstance(child, ast.Name) and child.id == "argv":
            return True
        if isinstance(child, ast.Call) and call_func_name(child) == "greet_name":
            return True
    return dynamic_hello(node)


def is_main_guard(node):
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if (not isinstance(test, ast.Compare) or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.Eq) or len(test.comparators) != 1):
        return False
    sides = (test.left, test.comparators[0])

    def is_dunder(item):
        return isinstance(item, ast.Name) and item.id == "__name__"

    def is_main(item):
        return isinstance(item, ast.Constant) and item.value == "__main__"

    return ((is_dunder(sides[0]) and is_main(sides[1]))
            or (is_dunder(sides[1]) and is_main(sides[0])))


def greeting_expr(greet_exists):
    if greet_exists:
        return ast.Call(
            func=ast.Name(id="greet", ctx=ast.Load()),
            args=[], keywords=[])
    return ast.Constant(value=GREETING)


def neuter_greet_name(fn, greet_exists):
    fn.body = [ast.Return(value=greeting_expr(greet_exists))]


def neuter_main(fn, greet_exists):
    # Print and return the default greeting so a test that only checks
    # the "Hello, " prefix still passes. The supplied name is unused.
    greeting = greeting_expr(greet_exists)
    printed = ast.Call(
        func=ast.Name(id="print", ctx=ast.Load()),
        args=[greeting], keywords=[])
    fn.body = [
        ast.Expr(value=printed),
        ast.Return(value=greeting_expr(greet_exists)),
    ]


def neuter_guard(node):
    node.body = [ast.Expr(value=ast.Call(
        func=ast.Name(id="main", ctx=ast.Load()),
        args=[], keywords=[]))]
    node.orelse = []


def neuter_source(source):
    """Return rewritten source, or None when no with-name path exists.

    greet_name() returns the default greeting. A name-aware main() prints
    and returns that same greeting. A name-aware __main__ guard only calls
    main(). Signatures stay so callers do not TypeError.
    """
    tree = ast.parse(source)
    fns = top_functions(tree)
    greet_exists = any(node.name == "greet" for node in fns)
    has_main = any(node.name == "main" for node in fns)
    changed = []
    for node in tree.body:
        if is_function(node) and node.name == "greet_name":
            neuter_greet_name(node, greet_exists)
            changed.append("greet_name")
        elif is_function(node) and node.name == "main" and is_name_aware(node):
            neuter_main(node, greet_exists)
            changed.append("main")
        elif is_main_guard(node) and is_name_aware(node) and has_main:
            neuter_guard(node)
            changed.append("__main__")
    if not changed:
        return None, []
    ast.fix_missing_locations(tree)
    rewritten = ast.unparse(tree) + "\n"
    compile(rewritten, "<g3-mutant>", "exec")
    return rewritten, changed


# ---------------------------------------------------------------- tests
def value_supplies_name(node):
    """True when an argument can carry a non-empty name."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value != ""
    if isinstance(node, (ast.List, ast.Tuple)):
        return any(value_supplies_name(item) for item in node.elts)
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, ast.Starred):
        return value_supplies_name(node.value)
    return True


def call_supplies_name(call):
    if any(kw.arg is None for kw in call.keywords):
        return True
    nodes = list(call.args) + [kw.value for kw in call.keywords]
    if not nodes:
        return False
    return any(value_supplies_name(node) for node in nodes)


def assigned_names(fn, predicate):
    found = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None or len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        if predicate(value):
            found.add(targets[0].id)
    return found


def element_is_hello_py(node, bound):
    if isinstance(node, ast.Name) and node.id in bound:
        return True
    if isinstance(node, ast.Starred):
        return element_is_hello_py(node.value, bound)
    return contains_const(node, "hello.py")


def seq_is_named_hello(elts, bound):
    for index, elt in enumerate(elts):
        if not element_is_hello_py(elt, bound):
            continue
        if any(value_supplies_name(item) for item in elts[index + 1:]):
            return True
    return False


def runs_hello_with_name(fn):
    """True when a runner actually launches hello.py with a non-empty argv.

    A list that merely mentions hello.py does not count. A no-arg launch
    does not count either: the default greeting still contains Hello, .
    """
    bound_paths = assigned_names(fn, lambda value: contains_const(value, "hello.py"))
    named_lists = []
    bound_argvs = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, (ast.List, ast.Tuple))
                and seq_is_named_hello(node.value.elts, bound_paths)):
            bound_argvs.add(node.targets[0].id)
        if isinstance(node, (ast.List, ast.Tuple)) and seq_is_named_hello(node.elts, bound_paths):
            named_lists.append(node)
    named_ids = {id(node) for node in named_lists}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or call_func_name(node) not in RUNNERS:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value.replace("\\", "/")
                marker = text.find("hello.py")
                if marker >= 0 and text[marker + len("hello.py"):].strip():
                    return True
        for child in ast.walk(node):
            if id(child) in named_ids:
                return True
            if isinstance(child, ast.Name) and child.id in bound_argvs:
                return True
    return False


def calls_named_helper(fn):
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if call_func_name(node) not in ("greet_name", "main"):
            continue
        if call_supplies_name(node):
            return True
    return False


def exercises_with_name(fn):
    return calls_named_helper(fn) or runs_hello_with_name(fn)


def asserts_hello_prefix(fn):
    bound = assigned_names(fn, lambda value: contains_const(value, HELLO_PREFIX))
    for node in ast.walk(fn):
        interesting = False
        if isinstance(node, ast.Assert):
            interesting = True
        elif isinstance(node, ast.Call) and call_func_name(node).startswith("assert"):
            interesting = True
        if not interesting:
            continue
        if contains_const(node, HELLO_PREFIX):
            return True
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in bound:
                return True
    return False


def qualifying_tests(source):
    """Test methods that exercise a non-empty name and assert Hello, ."""
    tree = ast.parse(source)
    found = []
    containers = []
    for node in tree.body:
        if is_function(node) and node.name.startswith("test"):
            containers.append(("", node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if is_function(item) and item.name.startswith("test"):
                    containers.append((node.name, item))
    for class_name, fn in containers:
        if exercises_with_name(fn) and asserts_hello_prefix(fn):
            found.append((class_name, fn.name))
    return found


def unittest_id(class_name, method):
    if class_name:
        return TEST_MODULE + "." + class_name + "." + method
    return TEST_MODULE + "." + method


def showed_failure(output, class_name, method):
    for line in output.splitlines():
        stripped = line.strip()
        failed = (
            stripped.startswith("FAIL:") or stripped.startswith("ERROR:")
            or stripped.endswith("... FAIL") or stripped.endswith("... ERROR")
        )
        if not failed or method not in stripped:
            continue
        before = stripped.split(method, 1)[0]
        if before and (before[-1].isalnum() or before[-1] == "_"):
            continue
        after = stripped.split(method, 1)[1]
        if after and (after[0].isalnum() or after[0] == "_"):
            continue
        if class_name and class_name not in stripped:
            continue
        return True
    return False


def run_unittest(root, ids=None):
    argv = [sys.executable, "-m", "unittest", "-v"]
    if ids:
        argv.extend(ids)
    else:
        argv.append(TEST_MODULE)
    return run_process(argv, root, timeout=60, extra_env=src_path_env(root))


def describe_tests(found):
    return "[" + ", ".join(unittest_id(cls, method) for cls, method in found) + "]"


# ---------------------------------------------------------------- blobs
def live_blobs():
    found = {}
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_WALK]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            path = Path(dirpath) / name
            try:
                rel = path.relative_to(REPO_ROOT).as_posix()
                found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                found[path.as_posix()] = "unreadable"
    return found


def ignore_noise(_directory, names):
    return [name for name in names
            if name in SKIP_WALK or name.endswith(".pyc")]


# ---------------------------------------------------------------- G1
def run_hello(args):
    return run_process(
        [sys.executable, HELLO_REL, *args], REPO_ROOT, timeout=30)


def short_out(proc):
    return one_line((proc.stdout or "")[:120])


def g1_named_stdout():
    hello = REPO_ROOT / HELLO_REL
    if not hello.is_file():
        return FAIL, "src/hello.py missing"
    named = run_hello([NAMED])
    noarg = run_hello([])
    empty = run_hello([""])
    runs = (named, noarg, empty)
    if any(could_not_start(proc) for proc in runs):
        return BLOCKED, (
            "could not run src/hello.py"
            + " named_rc=" + str(named.returncode)
            + " noarg_rc=" + str(noarg.returncode)
            + " empty_rc=" + str(empty.returncode)
            + " tail=" + one_line(tail(named))
        )
    named_ok = NAMED_GREETING in (named.stdout or "")
    noarg_ok = GREETING in (noarg.stdout or "")
    empty_ok = GREETING in (empty.stdout or "")
    status = PASS if named_ok and noarg_ok and empty_ok else FAIL
    detail = (
        "named=" + str(named_ok)
        + " noarg=" + str(noarg_ok)
        + " empty=" + str(empty_ok)
        + " named_rc=" + str(named.returncode)
        + " noarg_rc=" + str(noarg.returncode)
        + " empty_rc=" + str(empty.returncode)
        + " named_out=" + short_out(named)
        + " noarg_out=" + short_out(noarg)
        + " empty_out=" + short_out(empty)
    )
    return status, detail


# ---------------------------------------------------------------- G2
def g2_unittest_and_static():
    testp = REPO_ROOT / TEST_REL
    if not testp.is_file():
        return FAIL, "tests/test_hello.py missing"
    try:
        found = qualifying_tests(read_text(testp))
    except SyntaxError as exc:
        return FAIL, "test does not parse: " + str(exc)
    proc = run_unittest(REPO_ROOT)
    if could_not_start(proc):
        return BLOCKED, "unittest could not start rc=" + str(proc.returncode)
    live_ok = proc.returncode == 0
    status = PASS if live_ok and found else FAIL
    detail = (
        "unittest_exit=" + str(proc.returncode)
        + " qualifying=" + describe_tests(found)
        + " tail=" + one_line(tail(proc))
    )
    return status, detail


# ---------------------------------------------------------------- G3
def g3_mutation_turns_tests_red():
    before = live_blobs()
    try:
        status, detail = g3_body()
    except Exception as exc:
        status, detail = FAIL, "internal " + type(exc).__name__ + ": " + str(exc)
    after = live_blobs()
    if before != after:
        changed = sorted(
            (set(before) ^ set(after))
            | {key for key in before if key in after and before[key] != after[key]}
        )
        return FAIL, "live blobs changed: " + ",".join(changed) + "; " + detail
    return status, detail


def g3_body():
    hello = REPO_ROOT / HELLO_REL
    testp = REPO_ROOT / TEST_REL
    if not hello.is_file():
        return FAIL, "with-name path cannot be located; src/hello.py missing"
    try:
        source = read_text(hello)
        rewritten, changed = neuter_source(source)
    except SyntaxError as exc:
        return FAIL, "with-name path cannot be located; hello.py does not parse: " + str(exc)
    except Exception as exc:
        return FAIL, (
            "with-name path could not be rewritten: "
            + type(exc).__name__ + ": " + str(exc)
        )
    found = []
    parse_note = ""
    if testp.is_file():
        try:
            found = qualifying_tests(read_text(testp))
        except SyntaxError as exc:
            parse_note = " test_parse=" + str(exc)
    if rewritten is None:
        return FAIL, (
            "with-name path cannot be located"
            + " looked=greet_name,name-aware main,name-aware __main__"
            + " qualifying=" + describe_tests(found)
            + parse_note
        )
    if not testp.is_file():
        return FAIL, "mutated=" + ",".join(changed) + " but tests/test_hello.py missing"
    if parse_note:
        return FAIL, "mutated=" + ",".join(changed) + ";" + parse_note
    if not found:
        return FAIL, (
            "mutated=" + ",".join(changed)
            + " but no with-name test asserts " + HELLO_PREFIX
        )

    ids = [unittest_id(class_name, method) for class_name, method in found]
    live = run_unittest(REPO_ROOT, ids)
    if could_not_start(live):
        return BLOCKED, "live with-name tests could not start rc=" + str(live.returncode)
    if live.returncode != 0:
        return FAIL, (
            "with-name tests are not green before mutation"
            + " exit=" + str(live.returncode)
            + " tail=" + one_line(tail(live))
        )

    try:
        tmp = tempfile.TemporaryDirectory(prefix="check006-")
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__ + ": " + str(exc)
    with tmp:
        pack = Path(tmp.name) / "repo"
        try:
            shutil.copytree(REPO_ROOT, pack, ignore=ignore_noise)
        except OSError as exc:
            return BLOCKED, "temp copy failed: " + type(exc).__name__ + ": " + str(exc)
        dest = pack / HELLO_REL
        if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
            return FAIL, "temp copy aliased the live tree"
        dest.write_text(rewritten, encoding="utf-8", newline="\n")
        if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
            return FAIL, "mutant write landed in the live tree"
        mutant = run_unittest(pack, ids)
    if could_not_start(mutant):
        return BLOCKED, "mutant tests could not start rc=" + str(mutant.returncode)
    mutant_out = (mutant.stdout or "") + (mutant.stderr or "")
    red = [unittest_id(class_name, method) for class_name, method in found
           if showed_failure(mutant_out, class_name, method)]
    green = [unittest_id(class_name, method) for class_name, method in found
             if unittest_id(class_name, method) not in red]
    all_red = bool(found) and not green and mutant.returncode != 0
    status = PASS if all_red else FAIL
    detail = (
        "mutated=" + ",".join(changed)
        + " qualifying=" + describe_tests(found)
        + " live_exit=" + str(live.returncode)
        + " mutant_exit=" + str(mutant.returncode)
        + " red=" + str(red)
        + " still_green=" + str(green)
        + " mutant_tail=" + one_line(tail(mutant))
    )
    return status, detail


# ---------------------------------------------------------------- G4
def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def g4_regression():
    parts = []
    blocked = False
    ok = True
    before = live_blobs()
    for name in ("check_003.py", "check_004.py"):
        path = REPO_ROOT / "tools" / name
        if not path.is_file():
            ok = False
            parts.append(name + "=missing")
            continue
        proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=120)
        if could_not_start(proc):
            blocked = True
            ok = False
            parts.append(name + "=could not start rc " + str(proc.returncode))
            continue
        line = result_line((proc.stdout or "") + (proc.stderr or ""))
        this_ok = proc.returncode == 0
        ok = ok and this_ok
        parts.append(name + "=exit " + str(proc.returncode) + " " + repr(line))
    after = live_blobs()
    if before != after:
        ok = False
        parts.append("live blobs changed")
    if blocked and not ok:
        # A regression that did not exit 0 is FAIL. BLOCKED is only when
        # every regression process failed to start, so there is no result.
        if all(part.endswith("missing") or "could not start" in part for part in parts):
            return BLOCKED, "; ".join(parts)
    return (PASS if ok else FAIL), "; ".join(parts)


def run_gate(title, func):
    try:
        status, detail = func()
    except Exception as exc:
        status, detail = FAIL, "internal " + type(exc).__name__ + ": " + str(exc)
    gate(title, status, detail)


def main():
    run_gate(
        "G1 python src/hello.py Kyo contains Hello, Kyo!; "
        "no-arg and empty-string contain Hello, Gitmy!",
        g1_named_stdout)
    run_gate(
        "G2 unittest tests/test_hello.py is green and a test exercises "
        "the with-name path asserting Hello, ",
        g2_unittest_and_static)
    run_gate(
        "G3 temp-copy mutation ignores the name and the with-name tests go red",
        g3_mutation_turns_tests_red)
    run_gate(
        "G4 check_003.py and check_004.py exit 0",
        g4_regression)

    print("", flush=True)
    if FAILURES:
        print(
            "RESULT: FAIL (" + str(len(FAILURES)) + " block-level gate(s)): "
            + "; ".join(one_line(name) for name in FAILURES),
            flush=True)
        return 1
    print("RESULT: ALL PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
