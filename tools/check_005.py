#!/usr/bin/env python3
"""check_005 - offline toy of a roster / row-floor / exclusions gate.

The shape follows a nightly capture check: every roster id must appear in
the batch or be named on the exclusions list, and the batch must clear a
row floor. Row count is not completeness. A batch can pass the floor and
still miss roster ids.

This is committed fixtures only. It does not fetch a market list.
Stdlib only, offline, ASCII stdout. Live files are read, not written.
The missing-exclusions case uses a temp path that is never created.
"""

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FIX = REPO_ROOT / "fixtures" / "005"
ROSTER = FIX / "roster.csv"
COMPLETE = FIX / "batch_complete.csv"
FLOOR_BUT_MISSING = FIX / "batch_floor_but_missing.csv"
GAP_EXPLAINED = FIX / "batch_gap_explained.csv"
EXCLUSIONS = FIX / "exclusions.csv"

FLOOR = 8
KINDS = ("non-business-day", "event")

FAILURES = []


def one_line(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii").replace(
        "\r", "\\r").replace("\n", "\\n")


def gate(name, ok, detail=""):
    line = "[PASS] " if ok else "[FAIL] "
    print(line + one_line(name))
    if detail:
        print("  " + one_line(detail))
    if not ok:
        FAILURES.append(name)


def read_table(path):
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("bom")
    text = raw.decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def load_roster(path):
    rows = read_table(path)
    if not rows or "fund_id" not in rows[0]:
        return None, "roster missing fund_id"
    ids = []
    for row in rows:
        fund = (row.get("fund_id") or "").strip()
        if not fund:
            continue
        ids.append(fund)
    if len(ids) != len(set(ids)):
        return None, "roster duplicate"
    if not ids:
        return None, "roster empty"
    return ids, ""


def load_batch(path):
    rows = read_table(path)
    if not rows or "fund_id" not in rows[0]:
        return None, "batch missing fund_id"
    ids = []
    for row in rows:
        fund = (row.get("fund_id") or "").strip()
        if not fund:
            continue
        ids.append(fund)
    if not ids:
        return None, "batch empty"
    return ids, ""


def load_exclusions(path, roster_ids):
    rows = read_table(path)
    if not rows:
        return [], ""
    needed = ("fund_id", "kind", "reason")
    if any(name not in rows[0] for name in needed):
        return None, "exclusions header"
    allowed = set(roster_ids)
    found = []
    for row in rows:
        fund = (row.get("fund_id") or "").strip()
        kind = (row.get("kind") or "").strip()
        reason = (row.get("reason") or "").strip()
        if not fund and not kind and not reason:
            continue
        if fund not in allowed:
            return None, "exclusion id not on roster: " + fund
        if kind not in KINDS:
            return None, "exclusion kind: " + kind
        if not reason:
            return None, "exclusion reason empty: " + fund
        found.append(fund)
    return found, ""


def join_ids(ids):
    return ",".join(ids) if ids else "none"


def evaluate(roster, batch_ids, excluded_ids, floor):
    present = set(batch_ids)
    excluded = set(excluded_ids)
    missing = [fund for fund in roster if fund not in present]
    explained = [fund for fund in missing if fund in excluded]
    unexplained = [fund for fund in missing if fund not in excluded]
    detail = (
        "rows=" + str(len(batch_ids))
        + " floor=" + str(floor)
        + " explained=" + join_ids(explained)
        + " unexplained=" + join_ids(unexplained)
    )
    if len(batch_ids) < floor:
        return False, "decision=REJECT " + detail
    if unexplained:
        return False, "decision=REJECT " + detail
    return True, "decision=ACCEPT " + detail


def evaluate_files(roster_path, batch_path, exclusions_path, floor=FLOOR):
    if exclusions_path is None or not Path(exclusions_path).is_file():
        return False, "decision=REJECT exclusions list missing"
    try:
        roster, roster_err = load_roster(roster_path)
        if roster_err:
            return False, "decision=REJECT " + roster_err
        batch_ids, batch_err = load_batch(batch_path)
        if batch_err:
            return False, "decision=REJECT " + batch_err
        excluded, exc_err = load_exclusions(exclusions_path, roster)
        if exc_err:
            return False, "decision=REJECT " + exc_err
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        return False, "decision=REJECT " + type(exc).__name__
    return evaluate(roster, batch_ids, excluded, floor)


def main():
    ok, detail = evaluate_files(ROSTER, COMPLETE, EXCLUSIONS)
    gate("G1 complete batch covers the roster and meets the row floor",
         ok and "decision=ACCEPT" in detail and "rows=10" in detail, detail)

    ok, detail = evaluate_files(ROSTER, FLOOR_BUT_MISSING, EXCLUSIONS)
    gate("G2 floor-passing batch with an unexplained roster gap is rejected",
         (not ok) and "decision=REJECT" in detail and "rows=9" in detail
         and "unexplained=F10" in detail and "explained=F08,F09" in detail,
         detail)

    ok, detail = evaluate_files(ROSTER, GAP_EXPLAINED, EXCLUSIONS)
    gate("G3 gaps named on the exclusions list are accepted",
         ok and "decision=ACCEPT" in detail and "explained=F08,F09" in detail
         and "unexplained=none" in detail, detail)

    ok, detail = evaluate_files(ROSTER, COMPLETE, FIX / "exclusions-absent.csv")
    gate("G4 missing exclusions list is rejected",
         (not ok) and detail == "decision=REJECT exclusions list missing",
         detail)

    print("")
    if FAILURES:
        print("RESULT: FAILED (" + str(len(FAILURES)) + " gate(s)): "
              + "; ".join(one_line(name) for name in FAILURES))
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
