#!/usr/bin/env python3
"""Compare a changelog page with a previous version and print one JSON line."""

import argparse
import datetime
import html
import json
import re
import sys
import urllib.error
import urllib.request


_MAX_BYTES = 8000000
_MARK = ":" + "/" + "/"
_ARTICLE_RE = re.compile(r"<article\b", re.IGNORECASE)
_TIME_RE = re.compile(r"<time\b([^>]*)>", re.IGNORECASE)
_H2_RE = re.compile(r"<h2\b([^>]*)>", re.IGNORECASE)
_TOKEN_RE = re.compile(
    r"<h3\b[^>]*>(.*?)</h3>|<li\b[^>]*>(.*?)</li>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))"
)
_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")
_DATE_RE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})\Z", re.ASCII)
_VERSION_RE = re.compile(r"\Av(\d+)\.(\d+)\.(\d+)\Z", re.ASCII)
_PREVIOUS_RE = re.compile(r"\Av?(\d+)\.(\d+)\.(\d+)\Z", re.ASCII)
_FAIL_LINE = "Changelog 本次未能讀取"


class _Release:
    def __init__(self, version, numbers, date, entries):
        self.version = version
        self.numbers = numbers
        self.date = date
        self.entries = entries


def _build_parser():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--input-file")
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--text-line", action="store_true")
    return parser


def _parse_previous(value):
    if not isinstance(value, str):
        return None
    match = _PREVIOUS_RE.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _is_http_url(url):
    if not isinstance(url, str) or url == "":
        return False
    if any(char.isspace() for char in url):
        return False
    lowered = url.lower()
    https = "https" + _MARK
    http = "http" + _MARK
    if lowered.startswith(https):
        return len(lowered) > len(https)
    if lowered.startswith(http):
        return len(lowered) > len(http)
    return False


def _read_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(_MAX_BYTES + 1), None
    except OSError:
        return None, "read_failed"


def _fetch(url, timeout):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hello-routines/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(_MAX_BYTES + 1), None
    except urllib.error.HTTPError as exc:
        # HTTPError is a URLError. It has to be handled first.
        status = getattr(exc, "code", "")
        closer = getattr(exc, "close", None)
        if closer is not None:
            try:
                closer()
            except OSError:
                pass
        return None, "http_status " + str(status)
    except urllib.error.URLError:
        return None, "fetch_failed"
    except (OSError, ValueError):
        return None, "fetch_failed"


def _load(args):
    if args.url is not None:
        if not _is_http_url(args.url):
            return None, "bad_url"
        data, error = _fetch(args.url, args.timeout)
    else:
        data, error = _read_file(args.input_file)
    if error:
        return None, error
    if len(data) > _MAX_BYTES:
        return None, "too_large"
    return data.decode("utf-8", errors="replace"), None


def _attrs(raw):
    found = {}
    for match in _ATTR_RE.finditer(raw or ""):
        name = match.group(1).lower()
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        if value is None:
            value = ""
        if name not in found:
            found[name] = html.unescape(value)
    return found


def _valid_date(value):
    if not isinstance(value, str):
        return None
    match = _DATE_RE.fullmatch(value)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    return value


def _valid_version(value):
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        return None
    numbers = tuple(int(part) for part in match.groups())
    return value, numbers


def _collapse(text):
    return _SPACE_RE.sub(" ", text).strip()


def _clean_section(fragment):
    return _collapse(html.unescape(_TAG_RE.sub("", fragment)))


def _clean_entry(fragment):
    return _collapse(html.unescape(_TAG_RE.sub(" ", fragment)))


def _entries(block):
    section = None
    found = []
    for match in _TOKEN_RE.finditer(block):
        token = match.group(0)
        if token.lower().startswith("<h3"):
            section = _clean_section(match.group(1))
            continue
        if section is None:
            continue
        text = _clean_entry(match.group(2))
        if text:
            found.append((section, text))
    return found


def _blocks(text):
    starts = [match.start() for match in _ARTICLE_RE.finditer(text)]
    blocks = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        blocks.append(text[start:end])
    return blocks


def _parse_block(block):
    time_match = _TIME_RE.search(block)
    h2_match = _H2_RE.search(block)
    if time_match is None or h2_match is None:
        return None
    date = _valid_date(_attrs(time_match.group(1)).get("datetime"))
    version = _valid_version(_attrs(h2_match.group(1)).get("id"))
    if date is None or version is None:
        return None
    version_text, numbers = version
    return _Release(version_text, numbers, date, _entries(block))


def _releases(text):
    found = []
    seen = set()
    for block in _blocks(text):
        parsed = _parse_block(block)
        if parsed is None:
            continue
        if parsed.numbers in seen:
            return None
        seen.add(parsed.numbers)
        found.append(parsed)
    if not found:
        return None
    return found


def _prepare_text_stdout():
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        return


def _text_lines(version, date, entries, code):
    if code == 2:
        return [_FAIL_LINE]
    lines = [
        "Changelog 最新：" + version + "（" + date + "，本次讀網頁確認）"
    ]
    if code == 10:
        for item in entries:
            lines.append(
                "- [" + item["version"] + "] " + item["section"] + ": " + item["text"]
            )
    return lines


def _finish(version, date, changed, entries, error, code, text_line):
    if text_line:
        _prepare_text_stdout()
    payload = {
        "version": version,
        "date": date,
        "changed": changed,
        "new_entries": entries,
        "error": error,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    if text_line:
        for line in _text_lines(version, date, entries, code):
            sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return code


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    previous = _parse_previous(args.previous_version)
    if previous is None:
        return _finish(
            None, None, False, [], "bad_previous_version", 2, args.text_line
        )
    text, error = _load(args)
    if error:
        return _finish(None, None, False, [], error, 2, args.text_line)
    releases = _releases(text)
    if releases is None:
        return _finish(None, None, False, [], "parse_failed", 2, args.text_line)
    latest = max(releases, key=lambda item: item.numbers)
    entries = []
    for item in releases:
        if item.numbers <= previous:
            continue
        for section, body in item.entries:
            entries.append({
                "version": item.version,
                "section": section,
                "text": body,
            })
    if latest.numbers > previous:
        return _finish(
            latest.version, latest.date, True, entries, None, 10, args.text_line
        )
    return _finish(latest.version, latest.date, False, [], None, 0, args.text_line)


if __name__ == "__main__":
    sys.exit(main())
