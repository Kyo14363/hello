#!/usr/bin/env python3
"""Check whether caller-supplied relative paths exist for one date."""

import argparse
import datetime
import json
import os
import pathlib
import sys


_TOKEN_ISO = "{YYYY-MM-DD}"
_TOKEN_COMPACT = "{YYYYMMDD}"
_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--date")
    parser.add_argument("--pattern", action="append", required=True)
    return parser


def _parse_day(text):
    if not isinstance(text, str) or len(text) != 10:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    year_s = text[0:4]
    month_s = text[5:7]
    day_s = text[8:10]
    parts = (year_s, month_s, day_s)
    if not all(part.isascii() and part.isdigit() for part in parts):
        return None
    try:
        return datetime.date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return None


def _today():
    return datetime.datetime.now(_JST).date()


def _is_directory(text):
    if not isinstance(text, str) or text == "":
        return False
    try:
        return pathlib.Path(text).is_dir()
    except OSError:
        return False


def _absolute(pattern):
    if pattern[:1] in "/\\":
        return True
    if (
        len(pattern) >= 3
        and pattern[0].isalpha()
        and pattern[1] == ":"
        and pattern[2] in "/\\"
    ):
        return True
    return False


def _has_dotdot(pattern):
    return any(part == ".." for part in pattern.split("/"))


def _expand(pattern, iso, compact):
    if (
        not isinstance(pattern, str)
        or pattern == ""
        or "\\" in pattern
        or _absolute(pattern)
        or _has_dotdot(pattern)
    ):
        return None
    expanded = pattern.replace(_TOKEN_ISO, iso).replace(_TOKEN_COMPACT, compact)
    if (
        expanded == ""
        or "{" in expanded
        or "}" in expanded
        or "\\" in expanded
        or _absolute(expanded)
        or _has_dotdot(expanded)
    ):
        return None
    return expanded


def _inspect(root, rel):
    target = pathlib.Path(root)
    for part in rel.split("/"):
        target = target / part
    try:
        if not target.is_file():
            return False, None
        stamp = os.stat(target).st_mtime
    except OSError:
        return False, None
    when = datetime.datetime.fromtimestamp(int(stamp), tz=_JST)
    text = when.strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
    return True, text


def _write(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    sys.stdout.flush()


def _error(date_text, message):
    _write({
        "date": date_text,
        "files": [],
        "status": "error",
        "first_present": None,
        "missing": [],
        "error": message,
    })
    return 2


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.date is None:
        date_text = _today().isoformat()
    else:
        day = _parse_day(args.date)
        if day is None:
            return _error(None, "bad_date")
        date_text = day.isoformat()
    if not _is_directory(args.root):
        return _error(date_text, "bad_root")
    compact = date_text.replace("-", "")
    expanded = []
    for pattern in args.pattern:
        rel = _expand(pattern, date_text, compact)
        if rel is None:
            return _error(date_text, "bad_pattern")
        expanded.append(rel)
    files = []
    for index, rel in enumerate(expanded, start=1):
        exists, mtime = _inspect(args.root, rel)
        files.append({
            "order": index,
            "path": rel,
            "exists": exists,
            "mtime": mtime,
        })
    flags = [item["exists"] for item in files]
    if all(flags):
        status = "all"
    elif any(flags):
        status = "partial"
    else:
        status = "missing"
    first = None
    missing = []
    for item in files:
        if item["exists"]:
            if first is None:
                first = item["path"]
        else:
            missing.append(item["path"])
    _write({
        "date": date_text,
        "files": files,
        "status": status,
        "first_present": first,
        "missing": missing,
        "error": None,
    })
    if any(flags):
        return 0
    return 3


if __name__ == "__main__":
    sys.exit(main())
