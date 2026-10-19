#!/usr/bin/env python3
"""Select and run hello work-order gates for CI.

hello has no manifest and no accept_work_order.py. Each work order NNN is
tools/check_NNN.py, and its expected_paths live in the specs/*.md table.
Acceptance stays `python tools/check_NNN.py` exiting 0. This runner does
not import or edit those gates, and it does not execute Definition-of-done
text from a spec (that cell is data, not a command).

Changed paths come from the pull_request base/head SHAs, or from the push
before/after SHAs. A work order is selected when a changed path is one of
its expected_paths or is its check_NNN.py. If none match, every gate runs
as a regression.

When a work order is touched, every non-infra changed path must sit inside
that order's expected_paths. Infra paths are the allowlist below, not a
widened repo root.

Accepted gate bytes are pinned in tools/gate_acceptance_lock.json. CI
compares the files to that committed pin. It never rewrites the lock from
the live tree. A change needs a new acceptance entry: a reason and the new
sha256. Older entries must stay byte-for-byte.

Stdlib only. No network. ASCII stdout.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_RE = re.compile(r"^check_(\d{3})\.py$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ZERO_SHA = "0" * 40
LOCK_REL = "tools/gate_acceptance_lock.json"
INFRA_EXACT = (
    "README.md",
    "tools/ci_run_gates.py",
    LOCK_REL,
)
INFRA_PREFIXES = (
    ".github/",
    "docs/",
)
LOCK_TOP_KEYS = {"schema", "orders"}
LOCK_NODE_KEYS = {
    "acceptances", "check_path", "check_sha256", "spec_path", "spec_row_sha256",
}
LOCK_ENTRY_KEYS = {"check_sha256", "reason", "spec_row_sha256"}


class GateError(Exception):
    pass


def ascii_text(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def say(text=""):
    print(ascii_text(text), flush=True)


def norm_rel(path):
    text = str(path).replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise GateError("unsafe path: " + ascii_text(path))
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise GateError("unsafe path: " + ascii_text(path))
    return "/".join(parts)


class WorkOrder(object):
    def __init__(self, number, check_rel, expected_paths, spec_rel):
        self.number = number
        self.check_rel = check_rel
        self.expected_paths = tuple(expected_paths)
        self.spec_rel = spec_rel

    def match_paths(self):
        return set(self.expected_paths) | {self.check_rel}


def expected_paths_from_spec(text, spec_rel):
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        if "expected_paths" not in cells[0].lower():
            continue
        rows.append(cells[1])
    if not rows:
        return None
    if len(rows) != 1:
        raise GateError(spec_rel + " has " + str(len(rows)) + " expected_paths rows")
    paths = [norm_rel(item) for item in re.findall(r"`([^`]+)`", rows[0])]
    if not paths:
        raise GateError(spec_rel + " expected_paths cell has no backtick paths")
    return tuple(paths)


def discover(repo=None):
    repo = Path(REPO_ROOT if repo is None else repo)
    checks = {}
    tools = repo / "tools"
    if not tools.is_dir():
        raise GateError("tools/ is missing")
    for path in sorted(tools.iterdir()):
        match = CHECK_RE.match(path.name)
        if match and path.is_file():
            checks[match.group(1)] = "tools/" + path.name

    found = {}
    specs = repo / "specs"
    if not specs.is_dir():
        raise GateError("specs/ is missing")
    for path in sorted(specs.glob("*.md")):
        spec_rel = "specs/" + path.name
        paths = expected_paths_from_spec(
            path.read_text(encoding="utf-8"), spec_rel)
        if paths is None:
            continue
        numbers = []
        for item in paths:
            name = item.rsplit("/", 1)[-1]
            match = CHECK_RE.match(name)
            if match and item == "tools/" + name:
                numbers.append(match.group(1))
        if len(numbers) != 1:
            raise GateError(
                spec_rel + " expected_paths must list exactly one tools/check_NNN.py"
            )
        number = numbers[0]
        if number in found:
            raise GateError(
                "work order " + number + " claimed by both "
                + found[number].spec_rel + " and " + spec_rel
            )
        if number not in checks:
            raise GateError(
                spec_rel + " lists tools/check_" + number + ".py but that file is absent"
            )
        found[number] = WorkOrder(number, checks[number], paths, spec_rel)

    missing = sorted(set(checks) - set(found))
    if missing:
        raise GateError(
            "no expected_paths row for: "
            + ", ".join("tools/check_" + number + ".py" for number in missing)
        )
    return [found[number] for number in sorted(found)]


def select_orders(orders, changed):
    """Return (selected, mode, notes).

    mode is "touched" or "regression". changed is a list of repo-relative
    paths. None or an empty list means nothing to attribute, so every gate
    runs.
    """
    if not changed:
        return list(orders), "regression", []
    notes = []
    selected = []
    changed_set = set(changed)
    for order in orders:
        hit = sorted(changed_set & order.match_paths())
        if hit:
            selected.append(order)
            notes.append((order, hit))
    if not selected:
        return list(orders), "regression", []
    return selected, "touched", notes


def is_infra(path):
    if path in INFRA_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in INFRA_PREFIXES)


def scope_violations(orders, changed):
    """Per touched order, non-infra files outside that order's expected_paths.

    An empty changed list, or a diff that touches no work order, has no
    scope violation. Infra files are allowed beside any order.
    """
    if not changed:
        return []
    changed_set = set(changed)
    non_infra = sorted(path for path in changed_set if not is_infra(path))
    violations = []
    for order in orders:
        if not (changed_set & order.match_paths()):
            continue
        allowed = set(order.expected_paths) | {order.check_rel}
        outside = [path for path in non_infra if path not in allowed]
        if outside:
            violations.append((order, outside))
    return violations


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def spec_row_bytes(data, spec_rel):
    if isinstance(data, str):
        data = data.encode("utf-8")
    rows = []
    for raw in data.splitlines():
        line = raw.decode("utf-8")
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        if "expected_paths" not in cells[0].lower():
            continue
        rows.append(raw)
    if not rows:
        raise GateError(spec_rel + " has no expected_paths row")
    if len(rows) != 1:
        raise GateError(spec_rel + " has " + str(len(rows)) + " expected_paths rows")
    return rows[0]


def live_pins(repo, orders):
    repo = Path(repo)
    pins = {}
    for order in orders:
        check_path = repo / order.check_rel
        spec_path = repo / order.spec_rel
        if not check_path.is_file() or not spec_path.is_file():
            raise GateError("missing " + order.check_rel + " or " + order.spec_rel)
        row = spec_row_bytes(spec_path.read_bytes(), order.spec_rel)
        pins[order.number] = {
            "check": sha256_bytes(check_path.read_bytes()),
            "spec_row": sha256_bytes(row),
        }
    return pins


def strict_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key " + str(key))
        obj[key] = value
    return obj


def parse_lock_bytes(data):
    if data is None:
        return None, "lock file missing"
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=strict_pairs)
    except (UnicodeError, ValueError) as exc:
        return None, "lock JSON " + type(exc).__name__
    if not isinstance(obj, dict):
        return None, "lock file is not an object"
    return obj, ""


def parse_acceptances(node, label, problems):
    acc = node.get("acceptances") if isinstance(node, dict) else None
    if not isinstance(acc, list) or not acc:
        problems.append(label + " acceptances must be a non-empty list")
        return []
    parsed = []
    for index, entry in enumerate(acc):
        prefix = label + " acceptance[" + str(index) + "]"
        if not isinstance(entry, dict) or set(entry.keys()) != LOCK_ENTRY_KEYS:
            problems.append(prefix + " keys must be check_sha256, spec_row_sha256, reason")
            continue
        check_hash = entry.get("check_sha256") or ""
        spec_hash = entry.get("spec_row_sha256") or ""
        reason = entry.get("reason")
        if not HEX64.fullmatch(check_hash) or not HEX64.fullmatch(spec_hash):
            problems.append(prefix + " hash is not 64 lowercase hex")
        if not isinstance(reason, str) or not reason.strip():
            problems.append(prefix + " needs a non-empty reason")
        parsed.append({
            "check_sha256": check_hash,
            "spec_row_sha256": spec_hash,
            "reason": reason if isinstance(reason, str) else "",
        })
    return parsed


def order_lock_problems(order, node, live, base_node, base_pin, have_base):
    label = "order " + order.number
    problems = []
    if not isinstance(node, dict) or set(node.keys()) != LOCK_NODE_KEYS:
        return [label + " lock keys are wrong"]
    if node.get("check_path") != order.check_rel or node.get("spec_path") != order.spec_rel:
        problems.append(label + " path does not match the discovered spec")
    check_hash = node.get("check_sha256") or ""
    spec_hash = node.get("spec_row_sha256") or ""
    if not HEX64.fullmatch(check_hash) or not HEX64.fullmatch(spec_hash):
        problems.append(label + " pin is not 64 lowercase hex")
    if live is None:
        problems.append(label + " has no live pin")
        return problems
    if check_hash != live["check"] or spec_hash != live["spec_row"]:
        problems.append(
            label + " pin does not match the files"
            + " check " + check_hash + " != " + live["check"]
            + " spec_row " + spec_hash + " != " + live["spec_row"]
        )
    acceptances = parse_acceptances(node, label, problems)
    if acceptances:
        last = acceptances[-1]
        if last["check_sha256"] != check_hash or last["spec_row_sha256"] != spec_hash:
            problems.append(label + " last acceptance does not match the pin")
    if not have_base:
        return problems
    if base_pin is None:
        return problems
    if not isinstance(base_node, dict):
        if live != base_pin and not acceptances:
            problems.append(label + " changed without a re-acceptance entry")
        return problems
    base_problems = []
    base_acceptances = parse_acceptances(base_node, label + " base", base_problems)
    if base_problems:
        return problems + [label + " base acceptance history is unreadable"]
    if acceptances[:len(base_acceptances)] != base_acceptances:
        problems.append(label + " acceptance history was rewritten")
    changed = live != base_pin
    if changed:
        if len(acceptances) <= len(base_acceptances):
            problems.append(label + " changed without a new re-acceptance entry")
        elif acceptances:
            last = acceptances[-1]
            if (last["check_sha256"] != live["check"]
                    or last["spec_row_sha256"] != live["spec_row"]
                    or not last["reason"].strip()):
                problems.append(label + " re-acceptance entry does not carry the new hash and a reason")
    elif len(acceptances) != len(base_acceptances):
        problems.append(label + " acceptance history changed but the gate bytes did not")
    return problems


def lock_problems(orders, head_lock, live, base_lock, base_pins):
    """Return human-readable problems. base_pins is None when there is no base."""
    if not isinstance(head_lock, dict):
        return ["lock file missing or not an object"]
    problems = []
    if set(head_lock.keys()) != LOCK_TOP_KEYS:
        problems.append("lock keys must be schema and orders")
    if head_lock.get("schema") != 1:
        problems.append("lock schema must be 1")
    orders_obj = head_lock.get("orders")
    if not isinstance(orders_obj, dict):
        return problems + ["lock orders missing"]
    want = [order.number for order in orders]
    got = list(orders_obj.keys())
    if sorted(got) != sorted(want):
        problems.append(
            "lock orders " + ",".join(sorted(got))
            + " != discovered " + ",".join(want)
        )
    by_num = {order.number: order for order in orders}
    have_base = base_pins is not None
    base_orders = {}
    if isinstance(base_lock, dict) and isinstance(base_lock.get("orders"), dict):
        base_orders = base_lock["orders"]
    for number in sorted(set(got) & set(by_num)):
        base_pin = None if not have_base else base_pins.get(number)
        problems.extend(order_lock_problems(
            by_num[number],
            orders_obj[number],
            live.get(number),
            base_orders.get(number),
            base_pin,
            have_base,
        ))
    return problems


def fixture_spec(paths):
    cell = "、".join("`" + path + "`" for path in paths)
    return "| expected_paths | " + cell + " |\n"


def require(ok, detail):
    if not ok:
        raise GateError("fixture: " + detail)


def lock_node(check_hash, spec_hash, reason, acceptances=None):
    if acceptances is None:
        acceptances = [{
            "check_sha256": check_hash,
            "spec_row_sha256": spec_hash,
            "reason": reason,
        }]
    return {
        "acceptances": acceptances,
        "check_path": "tools/check_010.py",
        "check_sha256": check_hash,
        "spec_path": "specs/010-a.md",
        "spec_row_sha256": spec_hash,
    }


def fixture_self_test():
    sample = (
        "| Delivery location / expected_paths | "
        "`specs/001.md`、`tools/check_001.py` |\n"
        "| Definition of done | `python tools/check_001.py` exits 0 |\n"
        "expected_paths are not a table row\n"
    )
    parsed = expected_paths_from_spec(sample, "sample.md")
    require(
        parsed == ("specs/001.md", "tools/check_001.py"),
        "parser got " + repr(parsed),
    )

    with tempfile.TemporaryDirectory(prefix="gate-fixture-") as tmp:
        root = Path(tmp)
        (root / "specs").mkdir()
        (root / "tools").mkdir()
        (root / "data").mkdir()
        (root / "tools" / "check_010.py").write_text("# fixture\n", encoding="utf-8")
        (root / "tools" / "check_011.py").write_text("# fixture\n", encoding="utf-8")
        paths_010 = (
            "specs/010-a.md", "tools/check_010.py",
            "data/only010.txt", "data/shared.txt",
        )
        paths_011 = (
            "specs/011-b.md", "tools/check_011.py",
            "data/only011.txt", "data/shared.txt",
        )
        (root / "specs" / "010-a.md").write_text(fixture_spec(paths_010), encoding="utf-8")
        (root / "specs" / "011-b.md").write_text(fixture_spec(paths_011), encoding="utf-8")
        orders = discover(root)
        numbers = [order.number for order in orders]
        require(numbers == ["010", "011"], "discovered " + ",".join(numbers))

        selected, mode, _notes = select_orders(orders, ["data/only010.txt"])
        require(
            mode == "touched" and [item.number for item in selected] == ["010"],
            "unique path selected " + ",".join(item.number for item in selected),
        )
        selected, mode, _notes = select_orders(orders, ["data/shared.txt"])
        require(
            mode == "touched" and [item.number for item in selected] == ["010", "011"],
            "shared path selected " + ",".join(item.number for item in selected),
        )
        selected, mode, _notes = select_orders(orders, ["README.md"])
        require(
            mode == "regression" and [item.number for item in selected] == numbers,
            "unrelated path did not regress",
        )
        selected, mode, _notes = select_orders(orders, [])
        require(mode == "regression" and len(selected) == 2, "empty diff")

        require(
            scope_violations(orders, [
                "data/only010.txt", "README.md", "docs/GATE-DESIGN.md",
                ".github/workflows/gate.yml", "tools/ci_run_gates.py",
                LOCK_REL,
            ]) == [],
            "infra beside one order should pass",
        )
        require(scope_violations(orders, ["data/shared.txt"]) == [], "shared file")
        require(
            scope_violations(orders, ["tools/jev_smoke.py"]) == [],
            "unrelated file with no work order",
        )
        mixed = scope_violations(orders, ["data/only010.txt", "data/only011.txt"])
        mixed_got = sorted((item.number, tuple(paths)) for item, paths in mixed)
        require(
            mixed_got == [
                ("010", ("data/only011.txt",)),
                ("011", ("data/only010.txt",)),
            ],
            "cross-order scope got " + repr(mixed_got),
        )
        stray = scope_violations(orders, ["data/only010.txt", "tools/jev_smoke.py"])
        require(
            len(stray) == 1 and stray[0][0].number == "010"
            and stray[0][1] == ["tools/jev_smoke.py"],
            "stray file beside a work order",
        )

    check_a = "a" * 64
    spec_a = "b" * 64
    check_b = "c" * 64
    spec_b = "d" * 64
    order = WorkOrder(
        "010", "tools/check_010.py",
        ("tools/check_010.py", "data/only010.txt"), "specs/010-a.md",
    )
    orders = [order]
    live = {"010": {"check": check_a, "spec_row": spec_a}}
    head = {"schema": 1, "orders": {"010": lock_node(check_a, spec_a, "initial acceptance")}}
    require(lock_problems(orders, head, live, None, None) == [], "matching pin")

    drifted = {"010": {"check": check_b, "spec_row": spec_a}}
    drifted_problems = lock_problems(orders, head, drifted, None, None)
    require(any("does not match the files" in item for item in drifted_problems), "drift")

    empty_reason = lock_node(check_a, spec_a, "   ")
    empty_head = {"schema": 1, "orders": {"010": empty_reason}}
    require(
        any("reason" in item for item in lock_problems(orders, empty_head, live, None, None)),
        "empty reason",
    )

    base_live = {"010": {"check": check_a, "spec_row": spec_a}}
    require(
        lock_problems(orders, head, live, head, base_live) == [],
        "unchanged history",
    )
    rewritten = lock_node(check_a, spec_a, "rewritten reason")
    rewritten_head = {"schema": 1, "orders": {"010": rewritten}}
    require(
        any("rewritten" in item for item in lock_problems(
            orders, rewritten_head, live, head, base_live)),
        "rewritten history",
    )
    stale = lock_problems(
        orders, head,
        {"010": {"check": check_b, "spec_row": spec_b}},
        head, base_live,
    )
    require(
        any("without a new re-acceptance" in item or "does not match" in item for item in stale),
        "edit without a new entry",
    )
    old_entry = {
        "check_sha256": check_a,
        "spec_row_sha256": spec_a,
        "reason": "initial acceptance",
    }
    new_entry = {
        "check_sha256": check_b,
        "spec_row_sha256": spec_b,
        "reason": "re-accepted after the gate edit",
    }
    reaccepted = lock_node(check_b, spec_b, "", [old_entry, new_entry])
    reaccepted_head = {"schema": 1, "orders": {"010": reaccepted}}
    new_live = {"010": {"check": check_b, "spec_row": spec_b}}
    require(
        lock_problems(orders, reaccepted_head, new_live, head, base_live) == [],
        "appended re-acceptance",
    )
    require(
        any("missing" in item for item in lock_problems(orders, None, live, None, None)),
        "missing lock",
    )


def self_test(repo=None):
    repo = Path(REPO_ROOT if repo is None else repo)
    fixture_self_test()
    orders = discover(repo)
    if not orders:
        raise GateError("no work orders discovered")
    numbers = [order.number for order in orders]
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        raise GateError("work orders are not uniquely sorted")
    for order in orders:
        if order.check_rel not in order.expected_paths:
            raise GateError(order.check_rel + " missing from its expected_paths")
    say("SELF-TEST: PASS (" + str(len(orders)) + " work orders)")
    return orders


def git_out(repo, args):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GateError("git " + " ".join(args) + " failed: " + detail)
    return proc.stdout


def git_blob(repo, rev, rel):
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", rev + ":" + rel],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def ensure_commit(repo, rev):
    if not SHA_RE.fullmatch(rev or ""):
        raise GateError("refusing non-sha diff endpoint: " + ascii_text(rev))
    git_out(repo, ["rev-parse", "--verify", "--end-of-options", rev + "^{commit}"])
    return rev.lower()


def changed_between(repo, base, head, three_dot):
    """Files that differ.

    three_dot=True is the pull_request view: merge-base(base, head)..head,
    i.e. only what the branch itself changed. three_dot=False is the push
    view: the net tree difference from the previous tip to the new tip.
    """
    base = ensure_commit(repo, base)
    head = ensure_commit(repo, head)
    if three_dot:
        git_out(repo, ["merge-base", "--end-of-options", base, head])
        spec = base + "..." + head
    else:
        spec = base + ".." + head
    text = git_out(
        repo,
        ["diff", "--name-status", "--find-renames", "--end-of-options", spec],
    )
    paths = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise GateError("unparsed git diff line: " + ascii_text(line))
        for item in parts[1:]:
            paths.append(norm_rel(item))
    # Stable, de-duplicated. Rename entries contribute both sides.
    return sorted(set(paths)), base, head


def load_event():
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path:
        raise GateError("GITHUB_EVENT_PATH is not set")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("cannot read event payload: " + exc.__class__.__name__)


def changed_from_github(repo):
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event = load_event()
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        base = ((pr.get("base") or {}).get("sha"))
        head = ((pr.get("head") or {}).get("sha"))
        paths, base, head = changed_between(repo, base, head, three_dot=True)
        return paths, "pull_request " + base + "..." + head, base
    if event_name == "push":
        before = str(event.get("before") or "")
        after = str(event.get("after") or os.environ.get("GITHUB_SHA") or "")
        if before == ZERO_SHA:
            return None, "push has no previous commit", None
        paths, before, after = changed_between(repo, before, after, three_dot=False)
        return paths, "push " + before + ".." + after, before
    raise GateError("unsupported GITHUB_EVENT_NAME: " + ascii_text(event_name))


def resolve_changed(repo, args):
    modes = [bool(args.all), args.changed is not None, bool(args.base or args.head)]
    if sum(1 for item in modes if item) > 1:
        raise GateError("use only one of --all, --changed, or --base/--head")
    if args.base or args.head:
        if not args.base or not args.head:
            raise GateError("--base and --head are required together")
        # Local revs go through git rev-parse, then the same sha diff path.
        base = git_out(
            repo, ["rev-parse", "--verify", "--end-of-options", args.base]
        ).strip()
        head = git_out(
            repo, ["rev-parse", "--verify", "--end-of-options", args.head]
        ).strip()
        paths, base, head = changed_between(repo, base, head, three_dot=True)
        return paths, "diff " + base + "..." + head, base
    if args.all:
        return None, "--all", None
    if args.changed is not None:
        return [norm_rel(path) for path in args.changed], "--changed", None
    if os.environ.get("GITHUB_EVENT_NAME"):
        return changed_from_github(repo)
    return None, "no diff requested; defaulting to every gate", None


def pins_at(repo, rev, orders):
    pins = {}
    for order in orders:
        check_bytes = git_blob(repo, rev, order.check_rel)
        spec_bytes = git_blob(repo, rev, order.spec_rel)
        if check_bytes is None and spec_bytes is None:
            continue
        if check_bytes is None or spec_bytes is None:
            raise GateError("base has only part of work order " + order.number)
        row = spec_row_bytes(spec_bytes, order.spec_rel)
        pins[order.number] = {
            "check": sha256_bytes(check_bytes),
            "spec_row": sha256_bytes(row),
        }
    return pins


def evaluate_lock(repo, orders, base_sha):
    head_bytes = (Path(repo) / LOCK_REL).read_bytes() if (Path(repo) / LOCK_REL).is_file() else None
    head_lock, head_err = parse_lock_bytes(head_bytes)
    live = live_pins(repo, orders)
    if base_sha:
        base_bytes = git_blob(repo, base_sha, LOCK_REL)
        if base_bytes is None:
            base_lock, base_err = None, ""
        else:
            base_lock, base_err = parse_lock_bytes(base_bytes)
        if base_err and base_bytes is not None:
            return ["base " + base_err]
        base_pins = pins_at(repo, base_sha, orders)
    else:
        base_lock = None
        base_pins = None
    if head_err:
        return [head_err]
    return lock_problems(orders, head_lock, live, base_lock, base_pins)


def run_gate(repo, order, timeout):
    script = repo / order.check_rel
    if not script.is_file():
        say("[FAIL] " + order.check_rel + " -- missing")
        return 1
    say("")
    say("=== work order " + order.number + " : python3 " + order.check_rel + " ===")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(repo),
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        say("[FAIL] " + order.check_rel + " -- timeout " + str(timeout) + "s")
        return 124
    except OSError as exc:
        say("[FAIL] " + order.check_rel + " -- " + exc.__class__.__name__ + ": " + str(exc))
        return 127
    if proc.returncode == 0:
        say("GATE " + order.number + " PASS (" + order.check_rel + ")")
    else:
        say(
            "GATE " + order.number + " FAIL (" + order.check_rel
            + ") exit " + str(proc.returncode)
        )
    return proc.returncode


def print_orders(orders):
    for order in orders:
        say(order.number + " " + " ".join(order.expected_paths))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run the hello work-order gates.")
    parser.add_argument("--self-test", action="store_true", help="check discovery and selection, then exit")
    parser.add_argument("--list", action="store_true", help="print discovered work orders and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the gates that would run")
    parser.add_argument("--all", action="store_true", help="run every gate")
    parser.add_argument("--changed", action="append", help="repo-relative path; repeatable")
    parser.add_argument("--base", help="three-dot diff start (local PR-style use)")
    parser.add_argument("--head", help="three-dot diff end (local PR-style use)")
    parser.add_argument("--timeout", type=int, default=180, help="seconds per gate (default 180)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = REPO_ROOT
    try:
        orders = self_test(repo)
        if args.self_test:
            return 0
        if args.list:
            print_orders(orders)
            return 0
        changed, how, base_sha = resolve_changed(repo, args)
    except GateError as exc:
        say("CI GATE ERROR: " + str(exc))
        return 2

    say("diff: " + how)
    if changed is None:
        say("changed files: (none attributed)")
    else:
        say("changed files (" + str(len(changed)) + "):")
        for path in changed:
            say("  " + path)
        if not changed:
            say("  (empty diff)")

    selected, mode, notes = select_orders(orders, changed)
    if mode == "regression":
        say("selection: no work-order path touched; running every gate as regression")
    else:
        say("selection: touched work orders only")
        for order, hit in notes:
            say("  " + order.number + " via " + ", ".join(hit))
    skipped = [order.number for order in orders if order not in selected]
    say("will run: " + " ".join(order.check_rel for order in selected))
    if skipped:
        say("will skip: " + " ".join("check_" + number + ".py" for number in skipped))
    else:
        say("will skip: (none)")

    failed = []
    if changed is None:
        say("scope: skipped (no attributed diff)")
    else:
        violations = scope_violations(orders, changed)
        if not violations:
            say("scope: PASS")
        else:
            say("scope: FAIL")
            for order, outside in violations:
                say(
                    "  order " + order.number
                    + " outside expected_paths: " + ", ".join(outside)
                )
            say(
                "  infra allowance: "
                + ", ".join(INFRA_EXACT + INFRA_PREFIXES)
            )
            failed.append("scope")

    try:
        problems = evaluate_lock(repo, orders, base_sha)
    except GateError as exc:
        say("CI GATE ERROR: " + str(exc))
        return 2
    if not problems:
        say("lock: PASS (" + str(len(orders)) + " orders)")
    else:
        say("lock: FAIL")
        for problem in problems:
            say("  " + problem)
        failed.append("lock")

    if args.dry_run:
        say("")
        if failed:
            say("CI RESULT: FAIL (" + "; ".join(failed) + ")")
            return 1
        say("CI RESULT: DRY-RUN")
        return 0

    for order in selected:
        code = run_gate(repo, order, args.timeout)
        if code != 0:
            failed.append(order.number + " exit " + str(code))

    say("")
    if failed:
        say("CI RESULT: FAIL (" + "; ".join(failed) + ")")
        return 1
    say("CI RESULT: PASS (" + str(len(selected)) + " gate(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
