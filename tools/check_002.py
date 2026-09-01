#!/usr/bin/env python3
"""check_002 - headless agy needs skip-permissions.

Written before the work-order implementation.  G1 and G2 are expected red
until agy creates src/agy_headless.txt with artifacts that contain the
literal skip-permissions print-mode line from agy 1.1.23.  G4 constructs
the 001 pit: accept-edits stays, that line is gone, G2 must be red.

Stdlib only, offline, ASCII stdout.  Does not touch check_001 or 001
delivery files.
"""

import json
import re
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

GREETING = "Hello, Gitmy!"
MODEL = "gemini-3.7-flash-high"
FLAG_LINE = "agy-flag: dangerously-skip-permissions"
READ_PATH = "src/hello.py"
WRITE_PATH = "src/agy_headless.txt"
SKIP_LINE = (
    "Print mode: --dangerously-skip-permissions set, "
    "auto-approving all tool permissions"
)
ACCEPT_LINE = "Print mode: applying agent mode accept-edits"
CONV = "22222222-2222-2222-2222-222222222222"

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


def g1_headless_file_and_001_intact(root=None):
    root = Path(REPO_ROOT if root is None else root)
    hello = root / "src" / "hello.py"
    wrote_001 = root / "src" / "agy_wrote.txt"
    headless = root / "src" / "agy_headless.txt"
    remnants = (
        wrote_001.is_file()
        and (root / "artifacts" / "agy-001.json").is_file()
        and (root / "artifacts" / "agy-001.log").is_file()
        and (root / "tools" / "check_001.py").is_file()
    )
    if not hello.is_file():
        return False, "src/hello.py missing"
    if not headless.is_file():
        return False, "src/agy_headless.txt missing; remnants=" + str(remnants)
    hello_text = hello.read_text(encoding="utf-8")
    body = headless.read_text(encoding="utf-8")
    lines = [line for line in body.splitlines() if line.strip()]
    ok = (
        GREETING in hello_text
        and GREETING in body
        and FLAG_LINE in body
        and len(lines) >= 2
        and remnants
    )
    detail = (
        "hello_greeting=" + str(GREETING in hello_text)
        + "; headless_greeting=" + str(GREETING in body)
        + "; flag_line=" + str(FLAG_LINE in body)
        + "; nonempty_lines=" + str(len(lines))
        + "; remnants_001=" + str(remnants)
    )
    return ok, detail


def g2_skip_permissions_and_write(root=None):
    root = Path(REPO_ROOT if root is None else root)
    art_json = root / "artifacts" / "agy-002.json"
    art_log = root / "artifacts" / "agy-002.log"
    if not art_json.is_file() or not art_log.is_file():
        return False, "missing artifacts/agy-002.json or artifacts/agy-002.log"
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
    read_ok = READ_PATH in hay
    write_ok = WRITE_PATH in hay
    greeting_ok = GREETING in hay
    ok = (status_ok and conv_ok and tokens_ok and model_in_log
          and skip_ok and conv_in_log and read_ok and write_ok
          and greeting_ok)
    detail = (
        "status=" + status
        + "; conv=" + str(conv_ok)
        + "; tokens_ok=" + str(tokens_ok)
        + "; model_in_log=" + str(model_in_log)
        + "; skip_line=" + str(skip_ok)
        + "; accept_edits_present=" + str(ACCEPT_LINE in log_text)
        + "; conv_in_log=" + str(conv_in_log)
        + "; read_path=" + str(read_ok)
        + "; write_path=" + str(write_ok)
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
    'printmode.go:726] ' + ACCEPT_LINE + '\n'
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'server.go:1142] Created conversation ' + CONV + '\n'
    + READ_PATH + '\n'
    + GREETING + '\n'
    + WRITE_PATH + '\n'
)

PROXY_HEADLESS = GREETING + "\n" + FLAG_LINE + "\n"


def constructed_tree(parent, name):
    root = Path(parent) / name
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    write_utf8(root / "src" / "hello.py",
               'def main():\n    print("' + GREETING + '")\n')
    write_utf8(root / "src" / "agy_headless.txt", PROXY_HEADLESS)
    return root


def g3_proxy_edit_turns_g2_red(work):
    missing = constructed_tree(work, "file-only")
    ping_only = constructed_tree(work, "ping-only")
    write_utf8(ping_only / "artifacts" / "agy-002.json", PROXY_JSON)
    write_utf8(ping_only / "artifacts" / "agy-002.log", GOOD_LOG.replace(
        WRITE_PATH + "\n", ""))
    stripped = constructed_tree(work, "stripped-write")
    write_utf8(stripped / "artifacts" / "agy-002.json", PROXY_JSON)
    write_utf8(
        stripped / "artifacts" / "agy-002.log",
        GOOD_LOG.replace(WRITE_PATH + "\n", ""),
    )
    a_ok, a_detail = g2_skip_permissions_and_write(missing)
    b_ok, b_detail = g2_skip_permissions_and_write(ping_only)
    c_ok, c_detail = g2_skip_permissions_and_write(stripped)
    ok = (not a_ok) and (not b_ok) and (not c_ok)
    detail = (
        "file-only must be red: " + a_detail
        + " ;; ping-only must be red: " + b_detail
        + " ;; stripped-write must be red: " + c_detail
    )
    return ok, detail


def g4_accept_edits_without_skip_is_red(work):
    full = constructed_tree(work, "with-skip")
    write_utf8(full / "artifacts" / "agy-002.json", PROXY_JSON)
    write_utf8(full / "artifacts" / "agy-002.log", GOOD_LOG)
    pit = constructed_tree(work, "accept-only")
    write_utf8(pit / "artifacts" / "agy-002.json", PROXY_JSON)
    pit_log = "\n".join(
        line for line in GOOD_LOG.splitlines()
        if SKIP_LINE not in line
    ) + "\n"
    write_utf8(pit / "artifacts" / "agy-002.log", pit_log)
    full_ok, full_detail = g2_skip_permissions_and_write(full)
    pit_ok, pit_detail = g2_skip_permissions_and_write(pit)
    accept_left = ACCEPT_LINE in pit_log
    skip_gone = SKIP_LINE not in pit_log
    ok = full_ok and (not pit_ok) and accept_left and skip_gone
    detail = (
        "with-skip must be green: " + full_detail
        + " ;; accept-only must be red: " + pit_detail
        + "; accept_left=" + str(accept_left)
        + "; skip_gone=" + str(skip_gone)
    )
    return ok, detail


def main():
    g1_ok, g1_detail = g1_headless_file_and_001_intact()
    gate("G1 agy_headless.txt carries greeting and flag; 001 remnants stay",
         g1_ok, g1_detail)

    g2_ok, g2_detail = g2_skip_permissions_and_write()
    gate("G2 log has skip-permissions and the same run wrote agy_headless.txt",
         g2_ok, g2_detail)

    with tempfile.TemporaryDirectory(prefix="check002-") as tmp:
        g3_ok, g3_detail = g3_proxy_edit_turns_g2_red(tmp)
        gate("G3 file without a matching agy write record turns G2 red",
             g3_ok, g3_detail)

        g4_ok, g4_detail = g4_accept_edits_without_skip_is_red(tmp)
        gate("G4 accept-edits without skip-permissions turns G2 red",
             g4_ok, g4_detail)

    print("")
    if FAILURES:
        print("RESULT: FAILED (" + str(len(FAILURES)) + " gate(s)): "
              + "; ".join(one_line(name) for name in FAILURES))
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
