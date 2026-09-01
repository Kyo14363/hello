#!/usr/bin/env python3
"""check_001 - agy must read and write its own bytes.

Written before the work-order implementation.  G1 and G2 are expected red
until agy (gemini-3.7-flash-high) reads src/hello.py and creates
src/agy_wrote.txt, leaving matching artifacts.  Channel / Shell proxy
edits fail G2; G3 constructs that shape on a temp copy.

JSON keys and log phrases were taken from a real agy 1.1.23
`--output-format json --log-file` ping (status, conversation_id, usage,
printmode.go model=).  Tool-call records are matched as path text in
those two artifacts, not against an invented schema.

Stdlib only, offline, ASCII stdout.
"""

import json
import os
import re
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HELLO_PY = REPO_ROOT / "src" / "hello.py"
WROTE = REPO_ROOT / "src" / "agy_wrote.txt"
ART_JSON = REPO_ROOT / "artifacts" / "agy-001.json"
ART_LOG = REPO_ROOT / "artifacts" / "agy-001.log"

GREETING = "Hello, Gitmy!"
MODEL = "gemini-3.7-flash-high"
MODEL_LINE = "agy-model: gemini-3.7-flash-high"
READ_PATH = "src/hello.py"
WRITE_PATH = "src/agy_wrote.txt"

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


def g1_wrote_file_has_both_lines(root=None):
    root = Path(REPO_ROOT if root is None else root)
    hello = root / "src" / "hello.py"
    wrote = root / "src" / "agy_wrote.txt"
    if not hello.is_file():
        return False, "src/hello.py missing"
    if not wrote.is_file():
        return False, "src/agy_wrote.txt missing"
    hello_text = hello.read_text(encoding="utf-8")
    wrote_text = wrote.read_text(encoding="utf-8")
    hello_ok = GREETING in hello_text
    greeting_ok = GREETING in wrote_text
    model_ok = MODEL_LINE in wrote_text
    lines = [line for line in wrote_text.splitlines() if line.strip()]
    two_lines = len(lines) >= 2
    ok = hello_ok and greeting_ok and model_ok and two_lines
    detail = (
        "hello_greeting=" + str(hello_ok)
        + "; wrote_greeting=" + str(greeting_ok)
        + "; model_line=" + str(model_ok)
        + "; nonempty_lines=" + str(len(lines))
    )
    return ok, detail


def g2_artifacts_prove_agy_run(root=None):
    root = Path(REPO_ROOT if root is None else root)
    art_json = root / "artifacts" / "agy-001.json"
    art_log = root / "artifacts" / "agy-001.log"
    if not art_json.is_file() or not art_log.is_file():
        return False, "missing artifacts/agy-001.json or artifacts/agy-001.log"
    try:
        payload, json_raw = load_json(art_json)
    except Exception as exc:
        return False, "json: " + type(exc).__name__ + ": " + str(exc)
    log_text = art_log.read_text(encoding="utf-8", errors="replace")
    hay = slash_haystack(json_raw + "\n" + log_text)

    status = str(payload.get("status") or "")
    conv = str(payload.get("conversation_id") or "")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    tokens = usage.get("input_tokens")
    try:
        tokens_ok = int(tokens) > 0
    except (TypeError, ValueError):
        tokens_ok = False
    status_ok = status.upper() == "SUCCESS"
    conv_ok = bool(re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        conv))
    # Observed in agy 1.1.23 --log-file: printmode.go model="gemini-3.7-flash-high"
    model_in_log = (
        ('model="' + MODEL + '"') in log_text
        or ("Resolving model " + MODEL) in log_text
        or ("Model ID " + MODEL) in log_text
    )
    conv_in_log = bool(conv) and conv in log_text
    read_ok = READ_PATH in hay
    write_ok = WRITE_PATH in hay
    greeting_in_art = GREETING in hay
    ok = (status_ok and conv_ok and tokens_ok and model_in_log
          and conv_in_log and read_ok and write_ok and greeting_in_art)
    detail = (
        "status=" + status
        + "; conv=" + str(conv_ok)
        + "; tokens=" + str(tokens)
        + "; model_in_log=" + str(model_in_log)
        + "; conv_in_log=" + str(conv_in_log)
        + "; read_path=" + str(read_ok)
        + "; write_path=" + str(write_ok)
        + "; greeting_in_artifacts=" + str(greeting_in_art)
    )
    return ok, detail


PROXY_JSON = json.dumps({
    "conversation_id": "11111111-1111-1111-1111-111111111111",
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

PROXY_LOG = (
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'printmode.go:173] Print mode: starting (promptLength=10, '
    'model="gemini-3.7-flash-high", conversationID="")\n'
    'ERROR: logging before google.Init: I0901 00:00:00.000000       1 '
    'server.go:1142] Created conversation '
    '11111111-1111-1111-1111-111111111111\n'
)

PROXY_WROTE = GREETING + "\n" + MODEL_LINE + "\n"


def constructed_tree(parent, name):
    root = Path(parent) / name
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    write_utf8(root / "src" / "hello.py",
               'def main():\n    print("' + GREETING + '")\n')
    write_utf8(root / "src" / "agy_wrote.txt", PROXY_WROTE)
    return root


def g3_proxy_edit_turns_g2_red(work):
    missing_art = constructed_tree(work, "file-only")
    ping_only = constructed_tree(work, "ping-only")
    write_utf8(ping_only / "artifacts" / "agy-001.json", PROXY_JSON)
    write_utf8(ping_only / "artifacts" / "agy-001.log", PROXY_LOG)

    stripped = constructed_tree(work, "stripped-write")
    write_utf8(stripped / "artifacts" / "agy-001.json", PROXY_JSON)
    # Read path and greeting present; write path absent.
    write_utf8(
        stripped / "artifacts" / "agy-001.log",
        PROXY_LOG
        + "read_file " + READ_PATH + "\n"
        + GREETING + "\n",
    )

    a_ok, a_detail = g2_artifacts_prove_agy_run(missing_art)
    b_ok, b_detail = g2_artifacts_prove_agy_run(ping_only)
    c_ok, c_detail = g2_artifacts_prove_agy_run(stripped)
    ok = (not a_ok) and (not b_ok) and (not c_ok)
    detail = (
        "file-only must be red: " + a_detail
        + " ;; ping-only must be red: " + b_detail
        + " ;; stripped-write must be red: " + c_detail
    )
    return ok, detail


def main():
    g1_ok, g1_detail = g1_wrote_file_has_both_lines()
    gate("G1 agy_wrote.txt carries the greeting and model line",
         g1_ok, g1_detail)

    g2_ok, g2_detail = g2_artifacts_prove_agy_run()
    gate("G2 artifacts prove agy read hello.py and wrote agy_wrote.txt",
         g2_ok, g2_detail)

    with tempfile.TemporaryDirectory(prefix="check001-") as tmp:
        g3_ok, g3_detail = g3_proxy_edit_turns_g2_red(tmp)
        gate("G3 file without a matching agy write record turns G2 red",
             g3_ok, g3_detail)

    print("")
    if FAILURES:
        print("RESULT: FAILED (" + str(len(FAILURES)) + " gate(s)): "
              + "; ".join(one_line(name) for name in FAILURES))
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
