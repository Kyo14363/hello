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

Stdlib only. No network. ASCII stdout.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_RE = re.compile(r"^check_(\d{3})\.py$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ZERO_SHA = "0" * 40


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


def self_test(repo=None):
    sample = (
        "| Delivery location / expected_paths | "
        "`specs/001.md`、`tools/check_001.py` |\n"
        "| Definition of done | `python tools/check_001.py` exits 0 |\n"
        "expected_paths are not a table row\n"
    )
    parsed = expected_paths_from_spec(sample, "sample.md")
    if parsed != ("specs/001.md", "tools/check_001.py"):
        raise GateError("parser fixture mismatch: " + repr(parsed))

    orders = discover(repo)
    if not orders:
        raise GateError("no work orders discovered")
    numbers = [order.number for order in orders]
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        raise GateError("work orders are not uniquely sorted")

    for order in orders:
        if order.check_rel not in order.expected_paths:
            raise GateError(order.check_rel + " missing from its expected_paths")
        selected, mode, _notes = select_orders(orders, [order.check_rel])
        got = [item.number for item in selected]
        if mode != "touched" or got != [order.number]:
            raise GateError(
                order.check_rel + " selected " + ",".join(got) + " mode=" + mode
            )

    selected, mode, _notes = select_orders(orders, ["README.md"])
    if mode != "regression" or [item.number for item in selected] != numbers:
        raise GateError("unrelated path did not select every gate")

    selected, mode, _notes = select_orders(orders, [])
    if mode != "regression" or len(selected) != len(orders):
        raise GateError("empty diff did not select every gate")

    from collections import Counter
    counts = Counter(path for order in orders for path in order.expected_paths)
    shared = sorted(path for path, count in counts.items() if count > 1)
    if shared:
        path = shared[0]
        expect = [order.number for order in orders if path in order.expected_paths]
        selected, mode, _notes = select_orders(orders, [path])
        got = [item.number for item in selected]
        if mode != "touched" or got != expect:
            raise GateError("shared path " + path + " selected " + ",".join(got))

    # Pilot lock: breaking this deliverable must select only work order 001.
    # Selection itself still reads expected_paths; this only guards the fixture.
    only_001, mode, _notes = select_orders(orders, ["src/agy_wrote.txt"])
    if mode != "touched" or [item.number for item in only_001] != ["001"]:
        raise GateError(
            "src/agy_wrote.txt selected "
            + ",".join(item.number for item in only_001)
        )
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
        return paths, "pull_request " + base + "..." + head
    if event_name == "push":
        before = str(event.get("before") or "")
        after = str(event.get("after") or os.environ.get("GITHUB_SHA") or "")
        if before == ZERO_SHA:
            return None, "push has no previous commit"
        paths, before, after = changed_between(repo, before, after, three_dot=False)
        return paths, "push " + before + ".." + after
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
        return paths, "diff " + base + "..." + head
    if args.all:
        return None, "--all"
    if args.changed is not None:
        return [norm_rel(path) for path in args.changed], "--changed"
    if os.environ.get("GITHUB_EVENT_NAME"):
        return changed_from_github(repo)
    return None, "no diff requested; defaulting to every gate"


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
        changed, how = resolve_changed(repo, args)
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

    if args.dry_run:
        say("CI RESULT: DRY-RUN")
        return 0

    failed = []
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
