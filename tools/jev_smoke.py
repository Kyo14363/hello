#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jev_smoke.py - verification (smoke) test for TypeSafe "Jev"-style System One
decision APIs:  POST <base>/v1/systemone

Lines:
  --line cloud   TypeSafe cloud. Base https://api.typesafe.ai, header
                 "Authorization: Bearer <key>", default model jev-latest,
                 preflight GET /v1/models. (typesafe-sdk 0.7.2 constants.py +
                 _core/transport.py; https://api.typesafe.ai/openapi.json;
                 https://docs.typesafe.ai/api.md)
  --line ollama  Local Ollama >= 0.35. Base http://localhost:11434, key
                 "ollama" (public placeholder), default model nimble
                 (also tev1, tev1:0.8b). Preflight GET /api/version, /api/tags.

Python 3.10+ standard library only. Console output is ASCII only. The key is
never printed or written; error text is masked; C6 scans for leaks.

Criteria (per model; verdict PASS / FAIL / BLOCKED):
  (thresholds shown for set 1; set 2 uses 18/20, 18/20, 54/60)
  C1 connect : >= 7/8 of requests HTTP 200; every 200 body schema-valid, all
               probabilities in [0,1], choice (and score) probabilities sum
               to 1 +- 0.02.
  C2 correct : route >= 7/8 cases correct AND wake >= 7/8 correct AND urgency
               (ARGMAX of probabilities, not `score`) within 1 level for every
               case. Per case, the modal answer over the repeats is used.
  C3 stable  : each case repeated N times (--repeats, default 3); top answers
               (route choice, wake bool, urgency argmax) identical across all
               repeats for >= 90% of units. --stable-unit pair (default; 8 cases
               x 3 questions = 24 pairs) or case (a case is stable only if all
               3 questions are). Both numbers are always reported.
  Variants   : route wording orig | B (--variant, default both). With both,
               full results for both are reported and each model's verdict
               uses the better variant (C2 PASS first, then higher route+wake
               correct count, tie -> orig); the variant used is stated.
  C4 latency : p50/p95, with and without each model's first call (report only)
  C5 cost    : usage input/output token totals (credits not looked up);
               local: --mem-note text (report only)
  C6 security: stdout transcript and JSON report scanned for the key string;
               any hit = FAIL (the report is still written masked).
  "Can be added" = C1, C2, C3, C6 all PASS.
BLOCKED = unreachable, HTTP 401/402/403, missing key, model not pulled,
/v1/systemone 404 (Ollama < 0.35), Ollama < 0.35, 429/529 after one retry,
key over plain http to a non-loopback host.
Before sending, the question set is self-checked (every question needs
non-empty instructions; noul needs criteria.true/false; the cloud API answers
400 otherwise). A bad set is a config error: RESULT: FAIL, nothing is sent.
Question sets (--set): 1 = 8 cases (default; thresholds 7/8, 7/8, 90% of
pairs), 2 = 20 cases (thresholds 18/20, 18/20, 54/60 pairs; plus a report-only
WAKE-ACCEPTANCE section for cases 3-5). Thresholds are ratios of the set size.
The header prints question_set_sha256 = sha256 of the canonical JSON
(sort_keys, ensure_ascii=False, separators=(",",":")) of the set's cases,
expected answers and per-variant questions (instructions + criteria).
Before RESULT, one line per model:
  MODEL VERDICT <model>: PASS|FAIL|BLOCKED (variant=<orig|B>; failed=<C..|none>)
Last stdout line: RESULT: PASS (models passing: <list>) (exit 0) if ANY model
passes | else RESULT: FAIL (...) (exit 1) if any model FAILs | else
RESULT: BLOCKED (...) (exit 2).

Key file: ONE line (expected `apikey_...`, 108 chars). The first non-empty
line is read and stripped (UTF-8 with/without BOM, or UTF-16 with BOM).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import socket
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ==========================================================================
# Route option descriptions - ONE place; swap in the planner's official text.
# Keys are ASCII and are what the API returns as `choice`.
# ==========================================================================
ROUTE_CRITERIA = {
    "sheep": "規劃、寫 spec、協調派工；流程卡住或要重新安排誰做什麼",
    "pig": "寫閘門檢查腳本",
    "dog": "照 spec 改實作檔",
    "cat": "驗收並合併已完成的 PR",
    "owner": "奈神本人：bot 解決不了的事，例如斷線超過一小時、要登入或付款",
    "none": "不用交：結案、致謝、純分享",
}

TOOL_VERSION = "0.3.0"
SYSTEM_ONE_PATH = "/v1/systemone"
MODELS_PATH = "/v1/models"
CLOUD_DEFAULT_BASE_URL = "https://api.typesafe.ai"   # typesafe-sdk 0.7.2 DEFAULT_BASE_URL
CLOUD_DEFAULT_MODEL = "jev-latest"                   # typesafe-sdk 0.7.2 DEFAULT_MODEL
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "nimble"
OLLAMA_MIN_VERSION = (0, 35, 0)
OLLAMA_KEY = "ollama"
KEY_ENV = "TYPESAFE_API_KEY"
KEY_PREFIX, KEY_LEN = "apikey_", 108

PROB_TOL = 0.02

PASS, FAIL, BLOCKED, INFO = "PASS", "FAIL", "BLOCKED", "INFO"
EXIT_CODES = {PASS: 0, FAIL: 1, BLOCKED: 2}
URG_ASCII = ["low", "mid", "high"]

# ==========================================================================
# Questions and cases
# ==========================================================================
ROUTE_INSTRUCTIONS = {
    "orig": "這則團隊聊天訊息接下來應該交給誰處理？",
    "B": "這則訊息之後，下一個要動手的是誰？",
}
VARIANTS = ["orig", "B"]


def questions_for(variant: str) -> dict:
    """Same three questions for every case; only the route wording differs per variant."""
    return {
        "route": {
            "type": "choice",
            "instructions": ROUTE_INSTRUCTIONS[variant],
            "criteria": ROUTE_CRITERIA,
        },
        "wake": {
            "type": "noul",
            "instructions": "這則訊息是否需要現在就叫醒接手的人？",
            "criteria": {
                "true": "需要：接手的人現在就該動作（有人在等、流程卡住或要立刻處理）",
                "false": "不需要：沒有人需要現在動作（結案、致謝、純分享）",
            },
        },
        "urgency": {
            "type": "score",
            "instructions": "這則訊息有多緊急？",
            "criteria": ["低", "中", "高"],
        },
    }


QUESTIONS = questions_for("orig")

# expect: route=<ROUTE_CRITERIA key>, wake=<bool>, urgency=<0 低|1 中|2 高>
CASES_SET1 = [
    {"id": "case1_write_check004", "text": "spec #49 合了，請寫 check_004",
     "expect": {"route": "pig", "wake": True, "urgency": 1}},
    {"id": "case2_impl_farewell", "text": "閘門已宣告，請改 src/hello.py 加 farewell",
     "expect": {"route": "dog", "wake": True, "urgency": 1}},
    {"id": "case3_pr48_allpass", "text": "#48 已更新到最新 main，check_004 ALL PASS",
     "expect": {"route": "cat", "wake": True, "urgency": 1}},
    {"id": "case4_update_cloud_agent", "text": "閘門 #51 合了，請叫 #48 的雲端 agent 更新到新 main",
     "expect": {"route": "sheep", "wake": True, "urgency": 1}},
    {"id": "case5_pr_touched_gate", "text": "驗收發現 PR 改到 tools/check_004.py，BLOCKED",
     "expect": {"route": "sheep", "wake": True, "urgency": 2}},
    {"id": "case6_offline_1h", "text": "畚箕斷線已經超過一小時，接不回來",
     "expect": {"route": "owner", "wake": True, "urgency": 2}},
    {"id": "case7_closed_thanks", "text": "hello 004 結案，謝謝各位",
     "expect": {"route": "none", "wake": False, "urgency": 0}},
    {"id": "case8_x_daily", "text": "今天的 X 日報條目放上來給大家看",
     "expect": {"route": "none", "wake": False, "urgency": 0}},
]


# Set 2: 20 cases, same three questions / ROUTE_CRITERIA / wordings as set 1.
CASES_SET2 = [
    {"id": "s2c01_open_gate", "text": "spec 005 合了，main 是 abc1234，可以開閘門",
     "expect": {"route": "pig", "wake": True, "urgency": 1}},
    {"id": "s2c02_gate_rejected", "text": "閘門 check_005 被退回：G3 的反例沒有變紅",
     "expect": {"route": "pig", "wake": True, "urgency": 1}},
    {"id": "s2c03_gate_pr_merge", "text": "005 的閘門 PR 開好了，sha256 貼在內文，請合",
     "expect": {"route": "cat", "wake": True, "urgency": 1}},
    {"id": "s2c04_impl_pr_wait", "text": "實作 PR 推上去了，check_005 本機 ALL PASS，等驗收",
     "expect": {"route": "cat", "wake": True, "urgency": 1}},
    {"id": "s2c05_branch_updated", "text": "雲端 agent 說分支更新好了，head 是 9f2e1aa，衝突已解",
     "expect": {"route": "cat", "wake": True, "urgency": 1}},
    {"id": "s2c06_impl_g1_g3", "text": "閘門 #60 已合，請改 src/hello.py 讓 G1\u2013G3 變綠",
     "expect": {"route": "dog", "wake": True, "urgency": 1}},
    {"id": "s2c07_impl_rejected", "text": "實作被退回：diff 動到 README，超出允許的檔案",
     "expect": {"route": "dog", "wake": True, "urgency": 1}},
    {"id": "s2c08_agy_empty_diff", "text": "agy 跑完但 git diff 是空的，請換 grok CLI 重做",
     "expect": {"route": "dog", "wake": True, "urgency": 1}},
    {"id": "s2c09_who_does_it", "text": "小狗和小豬都說這題該對方做，請定一下誰做",
     "expect": {"route": "sheep", "wake": True, "urgency": 2}},
    {"id": "s2c10_spec_vs_gate", "text": "spec 的 R2 跟閘門的 G2 互相矛盾，要照哪個？",
     "expect": {"route": "sheep", "wake": True, "urgency": 2}},
    {"id": "s2c11_split_005", "text": "奈 神剛說新工單 005 要做 shout()，請拆給大家",
     "expect": {"route": "sheep", "wake": True, "urgency": 1}},
    {"id": "s2c12_main_red", "text": "main 上 check_003 突然變紅，不知道是哪個 PR 弄壞的",
     "expect": {"route": "sheep", "wake": True, "urgency": 2}},
    {"id": "s2c13_api_402", "text": "雲端 API 回 402，抵免額好像用完了",
     "expect": {"route": "owner", "wake": True, "urgency": 2}},
    {"id": "s2c14_owner_merge", "text": "這張要合進 kyo-work main，規則說要奈 神按",
     "expect": {"route": "owner", "wake": True, "urgency": 1}},
    {"id": "s2c15_console_login", "text": "之後有空要登入 console.typesafe.ai 才看得到扣款",
     "expect": {"route": "owner", "wake": False, "urgency": 0}},
    {"id": "s2c16_gate_typo", "text": "閘門說明有個錯字，不影響結果，之後順手改就好",
     "expect": {"route": "pig", "wake": False, "urgency": 0}},
    {"id": "s2c17_fyi_ollama", "text": "FYI 小狗：畚箕的 Ollama 已經升到 0.36，不用回",
     "expect": {"route": "dog", "wake": False, "urgency": 0}},
    {"id": "s2c18_ack", "text": "收到，我等你的 PR",
     "expect": {"route": "none", "wake": False, "urgency": 0}},
    {"id": "s2c19_wrap_up", "text": "今天先到這裡，大家辛苦了",
     "expect": {"route": "none", "wake": False, "urgency": 0}},
    {"id": "s2c20_running_local", "text": "我開始跑本機題組了，大概十分鐘",
     "expect": {"route": "none", "wake": False, "urgency": 0}},
]

CASES = CASES_SET1          # backwards-compatible alias (set 1)
ALL_CASES = CASES_SET1 + CASES_SET2

# Thresholds per set, as (numerator, denominator) ratios of the set size.
#   c1: share of requests that must be HTTP 200 (schema rules on top)
#   c2: share of cases with correct route AND (separately) correct wake
#   c3: share of stability units (pairs by default) identical across repeats
# Set 1 values are the v0.2.0 values (7/8, 7/8, 90%) - unchanged.
SETS = {
    "1": {"cases": CASES_SET1, "c1": (7, 8), "c2": (7, 8), "c3": (9, 10), "c3_label": "90%",
          "wake_acceptance": []},
    "2": {"cases": CASES_SET2, "c1": (18, 20), "c2": (18, 20), "c3": (54, 60), "c3_label": "54/60",
          "wake_acceptance": ["s2c03_gate_pr_merge", "s2c04_impl_pr_wait", "s2c05_branch_updated"]},
}


def _ratio(t) -> float:
    return t[0] / t[1]


def case_state(case: dict):
    return {"message": case["text"]}


def question_set_canonical(set_id: str) -> str:
    """Canonical JSON of a set: cases (id, state as sent, expected) and, per route
    wording variant, the full questions (instructions + criteria)."""
    doc = {"set": set_id,
           "cases": [{"id": c["id"], "state": case_state(c), "expect": c["expect"]} for c in SETS[set_id]["cases"]],
           "questions": {v: questions_for(v) for v in VARIANTS}}
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def question_set_sha256(set_id: str) -> str:
    return hashlib.sha256(question_set_canonical(set_id).encode("utf-8")).hexdigest()


# Optional --ping connectivity check (the Ollama blog example; not scored).
PING_STATE = {"ticket": "I was charged twice. Please refund the extra payment."}
PING_QUESTIONS = {
    "team": {"type": "choice", "instructions": "Which team should handle this ticket?",
             "criteria": {"billing": "Payments and refunds", "technical": "Bugs and integrations",
                          "other": "None of the above"}},
    "refund": {"type": "noul", "instructions": "Does the customer explicitly ask for a refund?",
               "criteria": {"true": "The customer asks for money back", "false": "No refund is requested"}},
    "urgency": {"type": "score", "instructions": "How urgent is this ticket?",
                "criteria": ["Routine", "Soon", "Urgent"]},
}


def _nonempty(x) -> bool:
    if isinstance(x, str):
        return bool(x.strip())
    if isinstance(x, (dict, list)):
        return bool(x)
    return False


def validate_question_set(questions) -> list[str]:
    """Pre-send self-check. The cloud API returns 400 when e.g. a noul lacks
    instructions or criteria, so refuse to send anything that would."""
    errs = []
    if not isinstance(questions, dict) or not questions:
        return ["questions must be a non-empty object"]
    for name, q in questions.items():
        if not isinstance(q, dict):
            errs.append("%s: not an object" % name)
            continue
        t = q.get("type")
        if t not in ("choice", "noul", "score"):
            errs.append("%s: bad type %r" % (name, t))
            continue
        if not _nonempty(q.get("instructions")):
            errs.append("%s: missing instructions" % name)
        c = q.get("criteria")
        if t == "choice":
            if not isinstance(c, dict) or not (2 <= len(c) <= 255):
                errs.append("%s: choice criteria must be an object with 2..255 options" % name)
            elif not all(isinstance(k, str) and k for k in c):
                errs.append("%s: choice option names must be non-empty strings" % name)
        elif t == "noul":
            if not isinstance(c, dict) or not _nonempty(c.get("true")) or not _nonempty(c.get("false")):
                errs.append("%s: noul criteria must have non-empty 'true' and 'false'" % name)
        else:
            if not isinstance(c, list) or not (2 <= len(c) <= 10) or not all(_nonempty(x) for x in c):
                errs.append("%s: score criteria must be a list of 2..10 non-empty levels" % name)
    return errs

# ==========================================================================
# Secret handling
# ==========================================================================

class Secret:
    """Holds the key; str()/repr() never reveal it."""

    def __init__(self, value: str | None, public: bool = False):
        self._v = value or None
        self.public = public  # True for the well-known placeholder "ollama"

    def get(self) -> str | None:
        return self._v

    def __bool__(self) -> bool:
        return bool(self._v)

    def __repr__(self) -> str:
        return "Secret(<redacted>)" if self._v else "Secret(None)"

    __str__ = __repr__


_BEARER_RE = re.compile(r"(?i)(bearer\s+)(?!<redacted>)[^\s\\\"',;]+")


def mask(text, secret: Secret | None = None) -> str:
    s = text if isinstance(text, str) else str(text)
    if secret is not None and secret.get() and not secret.public:
        k = secret.get()
        s = s.replace(k, "<redacted>").replace(urllib.parse.quote(k, safe=""), "<redacted>")
    return _BEARER_RE.sub(lambda m: m.group(1) + "<redacted>", s)


def ascii_safe(text: str, limit: int = 300) -> str:
    s = text.encode("ascii", "backslashreplace").decode("ascii").replace("\r", " ").replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def decode_key_file_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _valid_key(k: str) -> bool:
    return bool(k) and k.isascii() and k.isprintable() and not any(c.isspace() for c in k)


def parse_key_text(text: str) -> tuple[str | None, list[str]]:
    """Key file = ONE line: first non-empty line, stripped. Returns (key, warnings)."""
    text = text.replace("\ufeff", "")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None, ["key file is empty"]
    warns = []
    if len(lines) > 1:
        warns.append("key file has %d non-empty lines; using the first" % len(lines))
    k = lines[0]
    if not _valid_key(k):
        return None, warns + ["first line is not printable ASCII without whitespace"]
    if not (k.startswith(KEY_PREFIX) and len(k) == KEY_LEN):
        warns.append("key format unexpected (want %s..., %d chars); continuing" % (KEY_PREFIX, KEY_LEN))
    return k, warns


def load_key(line: str, key_file: str | None) -> tuple[Secret, str | None, list[str]]:
    """Return (secret, problem, warnings). problem None = usable key."""
    if key_file:
        try:
            with open(key_file, "rb") as fh:
                k, warns = parse_key_text(decode_key_file_bytes(fh.read()))
        except OSError as e:
            return Secret(None), "key file unreadable (%s)" % type(e).__name__, []
        if not k:
            return Secret(None), "no usable key in key file (%s)" % "; ".join(warns), []
        return Secret(k), None, warns
    if line == "ollama":
        return Secret(OLLAMA_KEY, public=True), None, []  # never forward TYPESAFE_API_KEY locally
    env = os.environ.get(KEY_ENV, "").strip()
    if env:
        if not _valid_key(env):
            return Secret(None), "%s is not printable ASCII without whitespace" % KEY_ENV, []
        return Secret(env), None, []
    return Secret(None), "missing key (use --key-file or set %s)" % KEY_ENV, []

# ==========================================================================
# HTTP
# ==========================================================================

def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip("[]").lower()
    return h in ("localhost", "::1") or h.startswith("127.")


class HttpResult:
    def __init__(self):
        self.status = None
        self.body_text = ""
        self.json = None
        self.error_kind = None    # unreachable | timeout | None
        self.error_detail = ""
        self.latency_ms = None
        self.headers = {}


def http_json(method: str, url: str, body, secret: Secret | None, timeout: float) -> HttpResult:
    res = HttpResult()
    data = None
    headers = {"Accept": "application/json", "User-Agent": "jev-smoke/" + TOOL_VERSION}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if secret is not None and secret.get():
        headers["Authorization"] = "Bearer " + secret.get()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    host = urllib.parse.urlsplit(url).hostname
    opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({})] if _is_loopback(host) else []))
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            res.status = resp.status
            res.headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        res.status = e.code
        try:
            raw = e.read()
        except Exception:
            raw = b""
        res.headers = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
    except (socket.timeout, TimeoutError):
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error_kind, res.error_detail = "timeout", "timed out after %.0fs" % timeout
        return res
    except urllib.error.URLError as e:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            res.error_kind, res.error_detail = "timeout", "timed out after %.0fs" % timeout
        else:
            res.error_kind = "unreachable"
            res.error_detail = mask("%s: %s" % (type(e.reason).__name__, e.reason), secret)
        return res
    except OSError as e:
        res.latency_ms = (time.perf_counter() - t0) * 1000
        res.error_kind, res.error_detail = "unreachable", mask("%s: %s" % (type(e).__name__, e), secret)
        return res
    res.latency_ms = (time.perf_counter() - t0) * 1000
    res.body_text = raw[:65536].decode("utf-8", errors="replace")
    try:
        res.json = json.loads(res.body_text) if res.body_text.strip() else None
    except ValueError:
        res.json = None
    return res

# ==========================================================================
# Response validation
# ==========================================================================

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _in01(x) -> bool:
    return _num(x) and -1e-9 <= x <= 1 + 1e-9


def _fmt(x) -> str:
    return ("%.3f" % x) if _num(x) else repr(x)


def validate_answer(question: dict, ans) -> tuple[list[str], list[str]]:
    """(errors, notes). Errors break C1; notes are informational."""
    errs, notes = [], []
    qtype = question["type"]
    if not isinstance(ans, dict):
        return ["answer is not an object"], notes
    if ans.get("type") != qtype:
        return ["type=%r, want %r" % (ans.get("type"), qtype)], notes
    if qtype == "noul":
        v = ans.get("noul")
        if not _num(v):
            errs.append("noul missing or not a number")
        elif not _in01(v):
            errs.append("noul=%r outside [0,1]" % v)
        return errs, notes
    probs, conf = ans.get("probabilities"), ans.get("confidence")
    if not _in01(conf):
        errs.append("confidence missing or outside [0,1]: %r" % (conf,))
    if not isinstance(probs, dict) or not probs:
        return errs + ["probabilities missing"], notes
    bad = [k for k, v in probs.items() if not _in01(v)]
    if bad:
        return errs + ["probabilities outside [0,1] for %s" % bad[:6]], notes
    total = sum(probs.values())
    if abs(total - 1.0) > PROB_TOL:
        errs.append("probabilities sum to %.4f (tol %.2f)" % (total, PROB_TOL))
    if qtype == "choice":
        crit = set(question["criteria"])
        if set(probs) != crit:
            errs.append("probability keys %s != criteria %s" % (sorted(probs), sorted(crit)))
        ch = ans.get("choice")
        if ch not in crit:
            errs.append("choice=%r not in criteria" % (ch,))
        elif probs.get(ch, -1) < max(probs.values()) - 1e-6:
            notes.append("choice=%s is not the highest-probability option" % ch)
    else:
        n = len(question["criteria"])
        want = {str(i) for i in range(n)}
        legend = ans.get("legend")
        if not isinstance(legend, dict) or set(legend) != want:
            errs.append("legend keys != %s" % sorted(want))
        if set(probs) != want:
            errs.append("probability keys %s != %s" % (sorted(probs), sorted(want)))
        sc = ans.get("score")
        if not _num(sc):
            errs.append("score missing or not a number")
        elif set(probs) == want:
            ws = sum(int(k) * v for k, v in probs.items())
            if abs(ws - sc) > 0.05:
                notes.append("score=%.3f differs from probability-weighted %.3f (argmax is used)" % (sc, ws))
    return errs, notes


def validate_response(questions: dict, data) -> tuple[list[str], list[str]]:
    errs, notes = [], []
    if not isinstance(data, dict):
        return ["response body is not a JSON object"], notes
    if not isinstance(data.get("model"), str):
        errs.append("model missing or not a string")
    u = data.get("usage")
    if not (isinstance(u, dict) and isinstance(u.get("input_tokens"), int) and isinstance(u.get("output_tokens"), int)):
        errs.append("usage.input_tokens/output_tokens missing or not integers")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        return errs + ["answers missing or not an object"], notes
    for qname, q in questions.items():
        if qname not in answers:
            errs.append("answers.%s missing" % qname)
            continue
        e, n = validate_answer(q, answers[qname])
        errs += ["answers.%s: %s" % (qname, x) for x in e]
        notes += ["answers.%s: %s" % (qname, x) for x in n]
    extra = sorted(set(answers) - set(questions))
    if extra:
        notes.append("unrequested answers present: %s" % extra)
    return errs, notes


def top_answers(answers: dict) -> dict:
    """route = choice; wake = noul > 0.5; urgency = argmax(probabilities), ties -> lower level.
    (`score` is NOT used for the verdict; it is only recorded.)"""
    w = answers.get("wake", {}).get("noul")
    p = answers.get("urgency", {}).get("probabilities") or {}
    try:
        levels = sorted(p, key=int)
        urg = int(max(levels, key=lambda k: p[k])) if levels else None
    except (ValueError, TypeError):
        urg = None
    return {"route": answers.get("route", {}).get("choice"),
            "wake": (w > 0.5) if _num(w) else None,
            "urgency": urg}


def parse_version(v: str):
    m = re.match(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?", v or "")
    return tuple(int(g or 0) for g in m.groups()) if m else None


def pctl(values, q):
    """Nearest-rank percentile."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]

# ==========================================================================
# Runner
# ==========================================================================

class Runner:
    def __init__(self, args, out, _selftest_inject_leak: bool = False):
        self.a = args
        self.out = out
        self.transcript = []
        self.secret = Secret(None)
        self.line_block = None
        self.model_block = {}
        self.preflight = {}
        self.warnings = []
        self.results = {}
        self.ping = {}
        self._inject_leak = _selftest_inject_leak

    def p(self, s: str):
        line = ascii_safe(mask(s, self.secret), limit=2000)
        self.transcript.append(line)
        self.out.write(line + "\n")
        self.out.flush()

    # -- one request, classified -------------------------------------------
    def call(self, model, state, questions):
        payload = {"model": model, "state": state, "questions": questions}
        attempts = 0
        while True:
            attempts += 1
            r = http_json("POST", self.base + SYSTEM_ONE_PATH, payload, self.secret, self.a.timeout)
            res = {"status": r.status, "latency_ms": r.latency_ms, "data": None, "headers": r.headers, "scope": None}
            if r.error_kind == "unreachable":
                return dict(res, state=BLOCKED, code="unreachable", detail=r.error_detail, scope="line")
            if r.error_kind == "timeout":
                return dict(res, state=FAIL, code="timeout", detail=r.error_detail)
            body = mask(r.body_text, self.secret)
            low = body.lower()
            if r.status in (429, 529) and attempts == 1:
                try:
                    delay = float(r.headers.get("retry-after", "2"))
                except ValueError:
                    delay = 2.0
                time.sleep(max(0.0, min(delay, 10.0)))
                continue
            if r.status in (429, 529):
                return dict(res, state=BLOCKED, code="rate_limited_%d" % r.status,
                            detail="http=%d body=%s" % (r.status, body[:200]), scope="line")
            if r.status in (401, 402, 403):
                return dict(res, state=BLOCKED, code="auth_%d" % r.status,
                            detail="http=%d body=%s" % (r.status, body[:200]), scope="line")
            if r.status in (400, 404) and "model" in low and ("not found" in low or "pull" in low):
                return dict(res, state=BLOCKED, code="model_not_pulled",
                            detail="http=%d body=%s" % (r.status, body[:200]), scope="model")
            if r.status == 404:
                return dict(res, state=BLOCKED, code="endpoint_not_found",
                            detail="http=404 for %s (Ollama < 0.35 or wrong --base-url) body=%s"
                                   % (SYSTEM_ONE_PATH, body[:120]), scope="line")
            if r.status is None or not (200 <= r.status < 300):
                return dict(res, state=FAIL, code="http_%s" % r.status,
                            detail="http=%s body=%s" % (r.status, body[:200]))
            if r.json is None:
                return dict(res, state=FAIL, code="bad_json", detail="non-JSON body=%s" % body[:120])
            return dict(res, state=PASS, code="ok", detail="http=%d" % r.status, data=r.json)

    # -- preflight -------------------------------------------------------------
    def preflight_ollama(self, models):
        r = http_json("GET", self.base + "/api/version", None, None, min(self.a.timeout, 15))
        if r.error_kind:
            self.line_block = (r.error_kind, "GET /api/version: %s" % r.error_detail)
            return
        ver = r.json.get("version") if isinstance(r.json, dict) else None
        self.preflight["ollama_version"] = ver
        pv = parse_version(ver) if isinstance(ver, str) else None
        if r.status == 200 and pv is not None:
            self.p("preflight: ollama version %s" % ver)
            if pv < OLLAMA_MIN_VERSION:
                self.line_block = ("ollama_too_old", "ollama %s < 0.35 (no /v1/systemone)" % ver)
                return
        else:
            self.p("preflight: could not read ollama version (http=%s); continuing" % r.status)
        t = http_json("GET", self.base + "/api/tags", None, None, min(self.a.timeout, 15))
        if t.status == 200 and isinstance(t.json, dict) and isinstance(t.json.get("models"), list):
            names = set()
            for m in t.json["models"]:
                for k in ("name", "model"):
                    v = m.get(k) if isinstance(m, dict) else None
                    if isinstance(v, str):
                        names.add(v)
                        if v.endswith(":latest"):
                            names.add(v[:-7])
            self.preflight["ollama_models"] = sorted(names)
            for mod in models:
                if mod not in names and mod + ":latest" not in names:
                    self.model_block[mod] = ("model_not_pulled", "'%s' not in /api/tags; run: ollama pull %s" % (mod, mod))
        else:
            self.p("preflight: could not list /api/tags (http=%s); skipping pulled-model check" % t.status)

    def preflight_cloud(self, models):
        r = http_json("GET", self.base + MODELS_PATH, None, self.secret, min(self.a.timeout, 30))
        if r.error_kind == "unreachable":
            self.line_block = ("unreachable", "GET %s: %s" % (MODELS_PATH, r.error_detail))
            return
        if r.status in (401, 402, 403):
            self.line_block = ("auth_%d" % r.status, "GET %s http=%d body=%s" % (
                MODELS_PATH, r.status, mask(r.body_text, self.secret)[:200]))
            return
        if r.status == 200 and isinstance(r.json, dict) and isinstance(r.json.get("models"), list):
            names = [m.get("name") for m in r.json["models"] if isinstance(m, dict)]
            self.preflight["cloud_models"] = names
            self.p("preflight: %s lists %s" % (MODELS_PATH, names))
            for mod in models:
                if mod not in names:
                    self.p("preflight: note '%s' not listed (versioned ids are accepted anyway)" % mod)
        else:
            self.p("preflight: %s http=%s; continuing" % (MODELS_PATH, r.status))

    # -- main --------------------------------------------------------------------
    def run(self) -> int:
        a = self.a
        self.started = datetime.now().astimezone()
        self.base = (a.base_url or (CLOUD_DEFAULT_BASE_URL if a.line == "cloud" else OLLAMA_DEFAULT_BASE_URL)).rstrip("/")
        self.models = a.model or [CLOUD_DEFAULT_MODEL if a.line == "cloud" else OLLAMA_DEFAULT_MODEL]
        self.set = SETS[a.set]
        self.cases = [c for c in self.set["cases"] if not a.case or c["id"] in a.case]
        self.qs_sha = question_set_sha256(a.set)
        self.variants = VARIANTS if a.variant == "both" else [a.variant]
        self.p("jev_smoke %s line=%s base_url=%s models=%s cases=%d repeats=%d variants=%s stable_unit=%s" % (
            TOOL_VERSION, a.line, self.base, ",".join(self.models), len(self.cases), a.repeats,
            ",".join(self.variants), a.stable_unit))
        self.p("set=%s question_set_sha256=%s" % (a.set, self.qs_sha))

        # pre-send self-check of the question set (cloud answers 400 otherwise)
        cfg = ["questions[%s].%s" % (v, e) for v in self.variants for e in validate_question_set(questions_for(v))]
        if a.ping:
            cfg += ["PING_QUESTIONS." + e for e in validate_question_set(PING_QUESTIONS)]
        if a.case:
            unknown = sorted(set(a.case) - {c["id"] for c in self.set["cases"]})
            if unknown:
                cfg.append("unknown --case ids %s" % unknown)
        if not self.cases:
            cfg.append("no cases selected")
        if a.repeats < 1:
            cfg.append("--repeats must be >= 1")
        if cfg:
            for e in cfg:
                self.p("config error (nothing sent): %s" % e)
            return self.finish(config_errors=cfg)

        if a.dry_run:
            for c in self.cases:
                self.p("DRY-RUN %s POST %s%s x%d" % (c["id"], self.base, SYSTEM_ONE_PATH, a.repeats))
            for v in self.variants:
                self.p(json.dumps({"model": self.models[0], "state": case_state(self.cases[0]),
                                   "questions": questions_for(v)}, ensure_ascii=True))
            return self.finish(dry=True)

        parts = urllib.parse.urlsplit(self.base)
        self.secret, key_problem, warns = load_key(a.line, a.key_file)
        for w in warns:
            self.p("key: %s" % w)
            self.warnings.append(w)
        self.p("auth: %s" % (("placeholder key 'ollama'" if self.secret.public else "key loaded (not shown)")
                             if self.secret else "no key"))
        if self._inject_leak and self.secret.get():
            # self-test only: write the raw key unmasked to prove C6 detects it
            raw = "SELFTEST-LEAK " + self.secret.get()
            self.transcript.append(raw)
            self.out.write(raw + "\n")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            self.line_block = ("bad_base_url", "base url must be http(s)://host[:port]")
        elif key_problem:
            self.line_block = ("missing_key", key_problem)
        elif a.line == "cloud" and parts.scheme == "http" and not _is_loopback(parts.hostname):
            self.line_block = ("insecure_base_url", "refusing to send the key over plain http to a non-loopback host")

        if not self.line_block and not a.skip_preflight:
            (self.preflight_ollama if a.line == "ollama" else self.preflight_cloud)(self.models)

        self.results = {m: [] for m in self.models}
        for model in self.models:
            if a.ping:
                self.do_ping(model)
            n_call = 0
            for variant in self.variants:
              qs = questions_for(variant)
              for rep in range(1, a.repeats + 1):
                for case in self.cases:
                    rec = {"case": case["id"], "repeat": rep, "variant": variant}
                    self.results[model].append(rec)
                    blk = self.line_block or self.model_block.get(model)
                    if blk:
                        rec.update(state=BLOCKED, code=blk[0], detail=blk[1])
                        if rep == 1:
                            self.p("[BLOCKED] %-10s %-4s r%d %-25s %s: %s" % (model, variant, rep, case["id"], blk[0], blk[1]))
                        continue
                    res = self.call(model, case_state(case), qs)
                    n_call += 1
                    rec.update(state=res["state"], code=res["code"], detail=res["detail"], http_status=res["status"],
                               latency_ms=round(res["latency_ms"], 1) if res["latency_ms"] is not None else None,
                               call_index=n_call)
                    if res["state"] != PASS:
                        self.p("[%s] %-10s %-4s r%d %-25s %s: %s" % (res["state"], model, variant, rep, case["id"],
                                                                    res["code"], res["detail"]))
                        if res["scope"] == "line":
                            self.line_block = (res["code"], res["detail"])
                        elif res["scope"] == "model":
                            self.model_block[model] = (res["code"], res["detail"])
                        continue
                    data = res["data"]
                    errs, notes = validate_response(qs, data)
                    d = data if isinstance(data, dict) else {}
                    rec.update(schema_errors=errs, notes=notes, response_model=d.get("model"), usage=d.get("usage"),
                               answers=d.get("answers"))
                    if errs:
                        rec["top"] = None
                        self.p("[FAIL] %-10s %-4s r%d %-25s %6.0fms schema: %s" % (
                            model, variant, rep, case["id"], res["latency_ms"], "; ".join(errs)))
                        continue
                    top = top_answers(d["answers"])
                    rec["top"] = top
                    rec["score"] = d["answers"]["urgency"].get("score")
                    rec["wake_noul"] = d["answers"]["wake"].get("noul")
                    exp = case["expect"]

                    def mark(k):
                        if top[k] == exp[k]:
                            return ""
                        want = URG_ASCII[exp[k]] if k == "urgency" else ("yes" if exp[k] is True else
                                                                          "no" if exp[k] is False else exp[k])
                        return "(want %s)" % want
                    urg = URG_ASCII[top["urgency"]] if top["urgency"] in (0, 1, 2) else top["urgency"]
                    self.p("[ OK ] %-10s %-4s r%d %-25s %6.0fms route=%s%s wake=%s(%s)%s urg=%s%s score=%s" % (
                        model, variant, rep, case["id"], res["latency_ms"], top["route"], mark("route"),
                        _fmt(d["answers"]["wake"]["noul"]), "yes" if top["wake"] else "no", mark("wake"),
                        urg, mark("urgency"), _fmt(rec["score"])))
                    for n in notes:
                        self.p("       note: %s" % n)
        return self.finish()

    def do_ping(self, model):
        blk = self.line_block or self.model_block.get(model)
        if blk:
            self.ping[model] = {"state": BLOCKED, "detail": "%s: %s" % blk}
            self.p("PING  %-10s BLOCKED %s: %s" % (model, blk[0], blk[1]))
            return
        res = self.call(model, PING_STATE, PING_QUESTIONS)
        if res["state"] == PASS:
            errs, _ = validate_response(PING_QUESTIONS, res["data"])
            team = None if errs else res["data"]["answers"]["team"].get("choice")
            st = FAIL if errs else PASS
            det = "; ".join(errs) or "http=200 %.0fms team=%s (blog expects billing)" % (res["latency_ms"], team)
        else:
            st, det = res["state"], "%s: %s" % (res["code"], res["detail"])
            if res["scope"] == "line":
                self.line_block = (res["code"], res["detail"])
            elif res["scope"] == "model":
                self.model_block[model] = (res["code"], res["detail"])
        self.ping[model] = {"state": st, "detail": det, "latency_ms": res["latency_ms"]}
        self.p("PING  %-10s %s %s" % (model, st, det))

    # -- evaluation ----------------------------------------------------------------
    def evaluate(self, model, variant):
        recs = [r for r in self.results.get(model, []) if r["variant"] == variant]
        total = len(recs)
        n_block = sum(1 for r in recs if r["state"] == BLOCKED)
        n_200 = sum(1 for r in recs if r.get("http_status") == 200)
        n_schema_bad = sum(1 for r in recs if r.get("schema_errors"))
        blk_txt = ", ".join("%s x%d" % kv for kv in sorted(Counter(r["code"] for r in recs if r["state"] == BLOCKED).items()))
        ev = {}
        c1t, c2t, c3t = self.set["c1"], self.set["c2"], self.set["c3"]
        # C1 connect
        if n_schema_bad:
            c1 = (FAIL, "%d/%d HTTP 200 but %d response(s) with schema errors" % (n_200, total, n_schema_bad))
        elif total and n_block > total * (1 - _ratio(c1t)):
            c1 = (BLOCKED, "%d/%d requests blocked (%s)" % (n_block, total, blk_txt))
        elif total and n_200 >= _ratio(c1t) * total - 1e-9:
            c1 = (PASS, "%d/%d HTTP 200, schema ok" % (n_200, total))
        else:
            c1 = (FAIL, "%d/%d HTTP 200 (need >= %d/%d)" % (n_200, total, c1t[0], c1t[1]))
        ev["C1_connect"] = {"state": c1[0], "detail": c1[1], "requests": total, "http_200": n_200,
                            "blocked": n_block, "schema_errors": n_schema_bad}
        # per-case modal answers over repeats
        per_case = {}
        for c in self.cases:
            crecs = [r for r in recs if r["case"] == c["id"]]
            tops = [r["top"] for r in crecs if r.get("top")]
            modal = {}
            for q in ("route", "wake", "urgency"):
                vals = [t[q] for t in tops]
                modal[q] = Counter(vals).most_common(1)[0][0] if vals else None
            per_case[c["id"]] = {"expect": c["expect"], "modal": modal, "tops": tops,
                                 "scores": [r.get("score") for r in crecs if r.get("top")],
                                 "blocked": any(r["state"] == BLOCKED for r in crecs)}
        any_blocked = any(v["blocked"] for v in per_case.values())
        nc = len(self.cases)
        # C2 correct
        md = lambda c, q: per_case[c["id"]]["modal"][q]
        rc = sum(1 for c in self.cases if md(c, "route") == c["expect"]["route"])
        wc = sum(1 for c in self.cases if md(c, "wake") == c["expect"]["wake"])
        ubad = [c["id"] for c in self.cases
                if not (isinstance(md(c, "urgency"), int) and abs(md(c, "urgency") - c["expect"]["urgency"]) <= 1)]
        uexact = sum(1 for c in self.cases if md(c, "urgency") == c["expect"]["urgency"])
        wrong_routes = ["%s:%s!=%s" % (c["id"].split("_")[0], md(c, "route"), c["expect"]["route"])
                        for c in self.cases if md(c, "route") != c["expect"]["route"]]
        wrong_wake = [c["id"].split("_")[0] for c in self.cases if md(c, "wake") != c["expect"]["wake"]]
        c2_ok = rc >= _ratio(c2t) * nc - 1e-9 and wc >= _ratio(c2t) * nc - 1e-9 and not ubad
        d2 = "route %d/%d, wake %d/%d, urgency(argmax) within 1 level %d/%d (exact %d/%d)" % (
            rc, nc, wc, nc, nc - len(ubad), nc, uexact, nc)
        c2 = (PASS, d2) if c2_ok else ((BLOCKED, d2 + "; some cases blocked") if any_blocked else (FAIL, d2))
        ev["C2_correct"] = {"state": c2[0], "detail": c2[1], "route_correct": rc, "wake_correct": wc,
                            "urgency_within1": nc - len(ubad), "urgency_exact": uexact, "cases": nc,
                            "wrong_routes": wrong_routes, "wrong_wake": wrong_wake, "urgency_off_by_2plus": ubad}
        # C3 stable
        R = self.a.repeats
        pairs_stable = cases_stable = 0
        unstable = []
        for c in self.cases:
            tops = per_case[c["id"]]["tops"]
            all_q = True
            for q in ("route", "wake", "urgency"):
                vals = [t[q] for t in tops]
                st = len(vals) == R and len(set(vals)) == 1
                pairs_stable += st
                if not st:
                    all_q = False
                    unstable.append("%s.%s=%s" % (c["id"].split("_")[0], q, vals))
            cases_stable += all_q
        n_pairs = nc * 3
        pr = pairs_stable / n_pairs if n_pairs else 0.0
        cr = cases_stable / nc if nc else 0.0
        ratio = pr if self.a.stable_unit == "pair" else cr
        d3 = "unit=%s: pairs %d/%d (%.1f%%), cases %d/%d (%.1f%%); need >= %s" % (
            self.a.stable_unit, pairs_stable, n_pairs, pr * 100, cases_stable, nc, cr * 100, self.set["c3_label"])
        if R < 2:
            c3 = (BLOCKED, "needs --repeats >= 2; " + d3)
        elif ratio >= _ratio(c3t) - 1e-9:
            c3 = (PASS, d3)
        elif any_blocked:
            c3 = (BLOCKED, d3 + "; some cases blocked")
        else:
            c3 = (FAIL, d3)
        ev["C3_stable"] = {"state": c3[0], "detail": c3[1], "unit": self.a.stable_unit, "repeats": R,
                           "pairs_stable": pairs_stable, "pairs_total": n_pairs, "pair_ratio": round(pr, 4),
                           "cases_stable": cases_stable, "cases_total": nc, "case_ratio": round(cr, 4),
                           "unstable": unstable}
        # C4 latency (report only)
        lat = [(r["call_index"], r["latency_ms"]) for r in recs
               if r.get("http_status") == 200 and r.get("latency_ms") is not None]
        allv = [v for _, v in lat]
        wo = [v for i, v in lat if i != 1]

        def st4(v):
            return {"n": len(v), "p50": round(statistics.median(v), 1) if v else None,
                    "p95": round(pctl(v, 0.95), 1) if v else None, "max": round(max(v), 1) if v else None}
        ev["C4_latency"] = {"state": INFO, "with_first_call": st4(allv), "without_first_call": st4(wo),
                            "first_call_ms": next((v for i, v in lat if i == 1), None),
                            "note": "the model's first call (model load / connection setup) belongs to the first variant run"}
        # C5 cost (report only): token totals
        us = [r["usage"] for r in recs if isinstance(r.get("usage"), dict)]
        tin = sum(u.get("input_tokens", 0) for u in us if isinstance(u.get("input_tokens"), int))
        tout = sum(u.get("output_tokens", 0) for u in us if isinstance(u.get("output_tokens"), int))
        ev["C5_cost"] = {"state": INFO, "input_tokens": tin, "output_tokens": tout, "responses": len(us),
                         "credits": "not looked up"}
        if self.a.line == "ollama":
            ev["C5_cost"]["mem_note"] = self.a.mem_note or "(none given; pass --mem-note)"
        return ev, per_case

    def wake_acceptance(self, model, variant):
        """Report-only: majority wake answer and mean noul for the set's wake-acceptance cases."""
        out = {}
        ids = {c["id"] for c in self.cases}
        for cid in self.set["wake_acceptance"]:
            if cid not in ids:
                continue
            recs = [r for r in self.results.get(model, []) if r["variant"] == variant and r["case"] == cid
                    and r.get("top") and _num(r.get("wake_noul"))]
            vals = [r["wake_noul"] for r in recs]
            yes = sum(1 for v in vals if v > 0.5)
            maj = None if not vals else ("yes" if yes * 2 > len(vals) else "no" if yes * 2 < len(vals) else "tie")
            exp = next(c["expect"]["wake"] for c in self.cases if c["id"] == cid)
            out[cid] = {"majority": maj, "yes_votes": yes, "n": len(vals),
                        "mean_noul": round(sum(vals) / len(vals), 4) if vals else None,
                        "expected": "yes" if exp else "no"}
        return out

    @staticmethod
    def _better(evs: dict) -> str:
        """better = C2 PASS first, then higher route+wake correct count; tie -> earlier (orig)."""
        def key(v):
            c2 = evs[v]["C2_correct"]
            return (c2["state"] == PASS, c2["route_correct"] + c2["wake_correct"])
        best = None
        for v in evs:
            if best is None or key(v) > key(best):
                best = v
        return best

    def finish(self, dry=False, config_errors=None) -> int:
        a = self.a
        report = {"tool": "jev_smoke", "tool_version": TOOL_VERSION,
                  "started_at": self.started.isoformat(timespec="seconds"),
                  "line": a.line, "base_url": getattr(self, "base", None), "models": getattr(self, "models", []),
                  "variants": getattr(self, "variants", []), "route_instructions": ROUTE_INSTRUCTIONS,
                  "route_criteria": ROUTE_CRITERIA, "case_ids": [c["id"] for c in getattr(self, "cases", [])],
                  "set": a.set, "question_set_sha256": question_set_sha256(a.set),
                  "question_set_sha256_all": {k: question_set_sha256(k) for k in SETS},
                  "thresholds": {k: SETS[a.set][k] for k in ("c1", "c2", "c3")},
                  "settings": {"repeats": a.repeats, "stable_unit": a.stable_unit, "timeout_s": a.timeout,
                               "prob_tol": PROB_TOL, "skip_preflight": a.skip_preflight, "ping": a.ping},
                  "auth": ("placeholder key 'ollama'" if self.secret.public else "key loaded (redacted)")
                          if self.secret else "none",
                  "warnings": self.warnings, "preflight": self.preflight}
        if config_errors:
            overall, result = FAIL, "RESULT: FAIL (config error, nothing sent: %s)" % "; ".join(config_errors)
            report["config_errors"] = config_errors
        elif dry:
            overall, result = BLOCKED, "RESULT: BLOCKED (dry-run, nothing sent)"
        else:
            report["ping"] = self.ping
            report["per_model"] = {}
            evals = {}
            for m in self.models:
                evals[m] = {}
                report["per_model"][m] = {"variants": {}, "requests": self.results[m]}
                for v in self.variants:
                    ev, per_case = self.evaluate(m, v)
                    evals[m][v] = ev
                    report["per_model"][m]["variants"][v] = {"criteria": ev, "cases": per_case}
            # C6 (whole run): scan transcript and serialized report for the key
            k = self.secret.get() if (self.secret and not self.secret.public) else None
            hit_stdout = bool(k) and any(k in l for l in self.transcript)
            hit_report = bool(k) and (k in json.dumps(report, ensure_ascii=True) or k in json.dumps(report, ensure_ascii=False))
            hits = [n for n, h in (("stdout", hit_stdout), ("report", hit_report)) if h]
            c6 = {"state": FAIL if hits else PASS,
                  "detail": ("key string found in: %s" % ", ".join(hits)) if hits else
                            ("no key string in stdout or report" if k else "no secret key in use (placeholder/none)"),
                  "scanned_stdout_lines": len(self.transcript)}
            report["C6_security"] = c6
            states, parts, passing, model_lines = [], [], [], []
            for m in self.models:
                for v in self.variants:
                    ev = evals[m][v]
                    self.p("-- %s / %s / variant %s" % (a.line, m, v))
                    for key in ("C1_connect", "C2_correct", "C3_stable"):
                        self.p("   %-11s %-7s %s" % (key, ev[key]["state"], ev[key]["detail"]))
                        if key == "C2_correct" and (ev[key]["wrong_routes"] or ev[key]["wrong_wake"]):
                            self.p("               wrong routes: %s | wrong wake: %s" % (
                                ", ".join(ev[key]["wrong_routes"]) or "-", ", ".join(ev[key]["wrong_wake"]) or "-"))
                        if key == "C3_stable" and ev[key]["unstable"] and ev[key]["state"] != BLOCKED:
                            self.p("               unstable: %s" % ", ".join(ev[key]["unstable"][:8]))
                    l4 = ev["C4_latency"]
                    self.p("   %-11s %-7s p50=%s p95=%s ms (n=%d, with first call) | p50=%s p95=%s ms (n=%d, without) first=%s ms" % (
                        "C4_latency", INFO, l4["with_first_call"]["p50"], l4["with_first_call"]["p95"],
                        l4["with_first_call"]["n"], l4["without_first_call"]["p50"], l4["without_first_call"]["p95"],
                        l4["without_first_call"]["n"], l4["first_call_ms"]))
                    c5 = ev["C5_cost"]
                    self.p("   %-11s %-7s tokens in=%d out=%d over %d responses; credits not looked up%s" % (
                        "C5_cost", INFO, c5["input_tokens"], c5["output_tokens"], c5["responses"],
                        ("; mem: " + c5["mem_note"]) if "mem_note" in c5 else ""))
                if self.set["wake_acceptance"]:
                    self.p("   WAKE-ACCEPTANCE (report only) %s" % m)
                    wa_all = {}
                    for v in self.variants:
                        wa = self.wake_acceptance(m, v)
                        wa_all[v] = wa
                        for cid, x in wa.items():
                            self.p("     variant %-4s %-25s majority=%s (%d/%d yes) mean_noul=%s expected=%s" % (
                                v, cid, x["majority"], x["yes_votes"], x["n"], _fmt(x["mean_noul"]), x["expected"]))
                    report["per_model"][m]["wake_acceptance"] = wa_all
                used = self._better(evals[m])
                ev = evals[m][used]
                gate = {"C1": ev["C1_connect"]["state"], "C2": ev["C2_correct"]["state"],
                        "C3": ev["C3_stable"]["state"], "C6": c6["state"]}
                verdict = FAIL if FAIL in gate.values() else BLOCKED if BLOCKED in gate.values() else PASS
                states.append(verdict)
                tot_in = sum(evals[m][v]["C5_cost"]["input_tokens"] for v in self.variants)
                tot_out = sum(evals[m][v]["C5_cost"]["output_tokens"] for v in self.variants)
                report["per_model"][m].update(verdict=verdict, can_be_added=verdict == PASS, variant_used=used,
                                              gate=gate, usage_totals={"input_tokens": tot_in, "output_tokens": tot_out})
                self.p("   C6_security %-7s %s" % (c6["state"], c6["detail"]))
                self.p("   tokens total (all variants) %s: in=%d out=%d" % (m, tot_in, tot_out))
                self.p("   VERDICT %s / %s: %s [variant %s used; C1=%s C2=%s C3=%s C6=%s]" % (
                    a.line, m, "CAN BE ADDED" if verdict == PASS else verdict + " (not addable)", used,
                    gate["C1"], gate["C2"], gate["C3"], gate["C6"]))
                failed = [kk for kk, vv in gate.items() if vv != PASS]
                model_lines.append("MODEL VERDICT %s: %s (variant=%s; failed=%s)" % (
                    m, verdict, used, ",".join(failed) if failed else "none"))
                if verdict != PASS:
                    parts.append("%s[%s]: %s" % (m, used, " ".join("%s=%s" % kv for kv in gate.items() if kv[1] != PASS)))
                else:
                    passing.append(m)
            # any model PASS -> PASS (exit 0); else any FAIL -> FAIL; else BLOCKED
            overall = PASS if PASS in states else FAIL if FAIL in states else BLOCKED
            reasons = Counter(r["code"] for m in self.models for r in self.results[m] if r["state"] == BLOCKED)
            if reasons:
                parts.append("blocked: " + ", ".join("%s x%d" % kv for kv in sorted(reasons.items())))
            report["models_passing"] = passing
            for ln in model_lines:
                self.p(ln)
            if overall == PASS:
                result = "RESULT: PASS (models passing: %s)" % ", ".join(passing)
            else:
                result = "RESULT: %s (line=%s; %s)" % (overall, a.line, "; ".join(parts))
        report["overall"] = overall
        report["result_line"] = result
        report["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if a.out:
            text = mask(json.dumps(report, ensure_ascii=True, indent=2), self.secret)
            k = self.secret.get() if (self.secret and not self.secret.public) else None
            if k and k in text:
                text = "{}"
            try:
                os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
                with open(a.out, "w", encoding="ascii") as fh:
                    fh.write(text + "\n")
                self.p("report: %s" % a.out)
            except OSError as e:
                self.p("report: could not write %s (%s)" % (a.out, type(e).__name__))
        self.p(result)
        return EXIT_CODES[overall]

# ==========================================================================
# Self-test: in-process fake server
# ==========================================================================

BLOG_SAMPLE_RESPONSE = {
    "model": "nimble",
    "answers": {
        "team": {"type": "choice", "choice": "billing",
                 "probabilities": {"billing": 0.985, "technical": 0.012, "other": 0.003}, "confidence": 0.922},
        "refund": {"type": "noul", "noul": 0.997},
        "urgency": {"type": "score", "score": 0.815, "legend": {"0": "Routine", "1": "Soon", "2": "Urgent"},
                    "probabilities": {"0": 0.378, "1": 0.429, "2": 0.193}, "confidence": 0.046},
    },
    "usage": {"input_tokens": 841, "output_tokens": 4},
}


def _choice_ans(names, pick):
    rest = 0.1 / (len(names) - 1)
    return {"type": "choice", "choice": pick, "probabilities": {n: (0.9 if n == pick else rest) for n in names},
            "confidence": 0.8}


def _score_ans(levels, lvl, score=None):
    n = len(levels)
    probs = {str(i): (0.9 if i == lvl else 0.1 / (n - 1)) for i in range(n)}
    return {"type": "score", "score": score if score is not None else sum(i * probs[str(i)] for i in range(n)),
            "legend": {str(i): c for i, c in enumerate(levels)}, "probabilities": probs, "confidence": 0.7}


def _fake_answers(case, mode, call_no, variant, model):
    exp = case["expect"]
    route = exp["route"]
    two = ("case1_write_check004", "case6_offline_1h")
    if mode in ("wrongroute", "nopullwrong") and case["id"] in two:
        route = "dog" if route != "dog" else "cat"              # 2/8 wrong in every variant -> C2 FAIL
    if mode == "wrongorig" and variant == "orig" and case["id"] in two:
        route = "dog"                                           # only orig wording wrong -> B used, PASS
    if mode == "badmodel" and model == "tev1:0.8b" and case["id"] in two:
        route = "dog"                                           # one model bad, the other fine
    if mode == "oneroute" and case["id"] == "case6_offline_1h":
        route = "sheep"                                         # 1/8 wrong -> still PASS
    if mode == "flip" and case["id"] in ("case1_write_check004", "case2_impl_farewell") and call_no == 2:
        route = "sheep"                                         # 2 unstable pairs: 22/24 pairs, 6/8 cases
    idx = next(i for sd in SETS.values() for i, c in enumerate(sd["cases"]) if c["id"] == case["id"])
    other = "none" if route != "none" else "sheep"
    mw = re.match(r"nwrong(\d+)$", mode)
    if mw and idx < int(mw.group(1)):
        route = other                                           # first K cases of the set wrong
    mf = re.match(r"nflip(\d+)$", mode)
    if mf and idx < int(mf.group(1)) and call_no == 2:
        route = other                                           # first K cases unstable (1 of 3 repeats)
    urg = exp["urgency"]
    if mode == "urg1":
        urg = urg + 1 if urg < 2 else 1                         # off by one everywhere -> PASS
    if mode == "urg2" and case["id"] == "case7_closed_thanks":
        urg = 2                                                 # off by two -> C2 FAIL
    score = 2.0 if mode == "scoredecoy" else None               # misleading score; argmax right -> PASS
    return {"route": _choice_ans(list(ROUTE_CRITERIA), route),
            "wake": {"type": "noul", "noul": 0.93 if exp["wake"] else 0.04},
            "urgency": _score_ans(QUESTIONS["urgency"]["criteria"], urg, score)}


class _FakeHandler(BaseHTTPRequestHandler):
    server_version = "fake-jev/2"

    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, text=None, headers=None):
        raw = (json.dumps(obj) if obj is not None else (text or "")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json" if obj is not None else "text/plain")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _split(self):
        parts = self.path.split("/", 2)
        return (parts[1] if len(parts) > 1 else ""), "/" + (parts[2] if len(parts) > 2 else "")

    def _auth_problem(self, mode):
        auth = self.headers.get("Authorization", "")
        if mode == "401":   # deliberately echoes the credential to prove masking
            return 401, {"detail": {"error_type": "authentication_error", "message": "Invalid API key: %s" % auth}}
        if not auth or mode == "403":
            return 403, {"detail": {"error_type": "authentication_error",
                                    "message": "Must supply an API key! Check your request and try again."}}
        if auth != "Bearer " + self.server.expected_key:
            return 401, {"detail": {"error_type": "authentication_error", "message": "bad key"}}
        if mode == "402":
            return 402, {"detail": {"error_type": "payment_required", "message": "Out of credits"}}
        return None

    def do_GET(self):
        mode, rest = self._split()
        if rest == "/api/version":
            return self._send(200, {"version": "0.34.2" if mode == "old" else "0.35.0"})
        if rest == "/api/tags":
            names = ["nimble:latest"] if mode == "nopull" else ["nimble:latest", "tev1:latest", "tev1:0.8b"]
            return self._send(200, {"models": [{"name": n, "model": n} for n in names]})
        if rest == MODELS_PATH:
            prob = self._auth_problem(mode)
            if prob:
                return self._send(*prob)
            return self._send(200, {"models": [{"name": "jev-latest", "description": "x", "release_date": "2026-09-15"}]})
        return self._send(404, text="404 page not found")

    def do_POST(self):
        mode, rest = self._split()
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        srv = self.server
        with srv.lock:
            srv.posts += 1
            n = srv.posts
        if rest != SYSTEM_ONE_PATH or mode == "old":
            return self._send(404, text="404 page not found")
        prob = self._auth_problem(mode)
        if prob:
            return self._send(*prob)
        if mode == "500":
            return self._send(500, {"detail": "internal error"})
        if mode == "429once" and n == 1:
            return self._send(429, {"detail": "slow down"}, headers={"retry-after": "0"})
        try:
            req = json.loads(body.decode("utf-8"))
        except ValueError:
            return self._send(422, {"detail": [{"loc": ["body"], "msg": "bad json", "type": "json"}]})
        qs = req.get("questions")
        qerr = validate_question_set(qs)
        if qerr:  # mirror the cloud's 400 for e.g. noul without instructions/criteria
            return self._send(400, {"detail": "; ".join(qerr)})
        model = req.get("model")
        if mode in ("nopull", "nopullwrong") and model != "nimble":
            return self._send(404, {"error": "model \"%s\" not found, try pulling it first" % model})
        if req.get("state") == PING_STATE:
            resp = json.loads(json.dumps(BLOG_SAMPLE_RESPONSE))
            resp["model"] = model
            return self._send(200, resp)
        case = next((c for c in ALL_CASES if case_state(c) == req.get("state")), None)
        if case is None:
            return self._send(422, {"detail": [{"loc": ["body", "state"], "msg": "unknown case", "type": "x"}]})
        rinstr = qs["route"]["instructions"]
        variant = next((v for v, t in ROUTE_INSTRUCTIONS.items() if t == rinstr), "?")
        with srv.lock:
            key = (model, case["id"], rinstr)
            srv.per_case[key] = srv.per_case.get(key, 0) + 1
            call_no = srv.per_case[key]
        ans = _fake_answers(case, mode, call_no, variant, model)
        if mode == "missing":
            ans.pop("urgency")
        elif mode == "badprob":
            ans["route"]["probabilities"] = {k: v * 1.3 for k, v in ans["route"]["probabilities"].items()}
        elif mode == "noulrange":
            ans["wake"]["noul"] = 1.7
        return self._send(200, {"model": model, "answers": ans, "usage": {"input_tokens": 300, "output_tokens": 6}})


def _start_fake(expected_key: str):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    srv.expected_key, srv.lock, srv.posts, srv.per_case = expected_key, threading.Lock(), 0, {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def self_test(out) -> int:
    fake_key = KEY_PREFIX + ("SeLfTeSt0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" * 2)[:KEY_LEN - len(KEY_PREFIX)]
    assert len(fake_key) == KEY_LEN

    def w(s):
        out.write(s + "\n")
        out.flush()
    w("jev_smoke %s self-test (fake server on 127.0.0.1, fake key, nothing leaves this machine)" % TOOL_VERSION)
    mismatches = []

    # unit: one-line key file
    variants = [(fake_key + "\n", fake_key, False), ("\ufeff  %s  \r\n" % fake_key, fake_key, False),
                ("\n\n%s\n\n" % fake_key, fake_key, False), (fake_key + "\nsecond line\n", fake_key, True),
                ("apikey_short\n", "apikey_short", True), ("", None, True), ("two words here\n", None, True)]
    bad = [i for i, (txt, want, ww) in enumerate(variants)
           if parse_key_text(txt)[0] != want or bool(parse_key_text(txt)[1]) != ww]
    if parse_key_text(decode_key_file_bytes((fake_key + "\r\n").encode("utf-16")))[0] != fake_key:
        bad.append("utf16")
    if bad:
        mismatches.append("unit_keyfile_one_line")
    w("SELFTEST %-32s %s (%d variants + utf-16)" % ("unit_keyfile_one_line", "ok" if not bad else "MISMATCH %s" % bad, len(variants)))

    # unit: question-set self-check
    qbad = []
    if any(validate_question_set(questions_for(v)) for v in VARIANTS) or validate_question_set(PING_QUESTIONS):
        qbad.append("shipped questions invalid")
    for path, desc in ((("wake", "instructions"), "noul without instructions"), (("wake", "criteria"), "noul without criteria"),
                       (("route", "instructions"), "choice without instructions"), (("urgency", "instructions"), "score without instructions")):
        b = json.loads(json.dumps(QUESTIONS))
        del b[path[0]][path[1]]
        if not validate_question_set(b):
            qbad.append(desc + " accepted")
    b = json.loads(json.dumps(QUESTIONS))
    b["wake"]["criteria"] = {"true": "x"}
    if not validate_question_set(b):
        qbad.append("noul without criteria.false accepted")
    if qbad:
        mismatches.append("unit_question_set_check")
    w("SELFTEST %-32s %s" % ("unit_question_set_check", "ok" if not qbad else "MISMATCH %s" % qbad))

    srv, srv_o = _start_fake(fake_key), _start_fake(OLLAMA_KEY)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    obase = "http://127.0.0.1:%d" % srv_o.server_address[1]
    tmp = tempfile.mkdtemp(prefix="jev_selftest_")
    keyfile = os.path.join(tmp, "key.txt")
    with open(keyfile, "w", encoding="utf-8") as fh:
        fh.write(fake_key + "\n")
    nokey = os.path.join(tmp, "nokey.txt")
    with open(nokey, "w", encoding="utf-8") as fh:
        fh.write("\n")
    dead = "http://127.0.0.1:%d" % _free_port()
    two = ["--model", "tev1:0.8b", "--model", "tev1"]
    K = ["--key-file", keyfile]
    O = lambda mode: ["--line", "ollama", "--base-url", obase + "/" + mode]
    C = lambda mode: ["--line", "cloud", "--base-url", base + "/" + mode]

    def pm(rep, m):
        return rep["per_model"][m]

    def crit(rep, m, v, c):
        return pm(rep, m)["variants"][v]["criteria"][c]
    # (name, argv, expected overall, inject_leak, extra report check)
    S = [
        ("ollama_ok_2_models_ping", O("ok") + two + ["--ping", "--mem-note", "16GB VRAM"], PASS, False,
         lambda r, t: all(pm(r, m)["verdict"] == PASS for m in ("tev1:0.8b", "tev1")) and r["ping"]["tev1"]["state"] == PASS
         and "models passing: tev1:0.8b, tev1" in t and "WAKE-ACCEPTANCE" not in t),
        ("cloud_ok_keyfile", C("ok") + K, PASS, False,
         lambda r, t: pm(r, "jev-latest")["usage_totals"]["input_tokens"] == 300 * 48
         and ("set=1 question_set_sha256=" + question_set_sha256("1")) in t and r["thresholds"]["c1"] == [7, 8]),
        ("cloud_ok_env_key", C("ok"), PASS, False, None),
        ("cloud_retry_after_429", C("429once") + K, PASS, False, None),
        ("route_7_of_8_still_pass", O("oneroute"), PASS, False,
         lambda r, t: crit(r, "nimble", "orig", "C2_correct")["route_correct"] == 7),
        ("urgency_off_by_1_pass", O("urg1"), PASS, False, None),
        ("score_decoy_argmax_used", O("scoredecoy"), PASS, False, None),
        ("C3_pair_default_22of24_pass", O("flip"), PASS, False,
         lambda r, t: crit(r, "nimble", "orig", "C3_stable")["pairs_stable"] == 22
         and crit(r, "nimble", "orig", "C3_stable")["cases_stable"] == 6 and r["settings"]["stable_unit"] == "pair"),
        ("better_variant_B_used", O("wrongorig"), PASS, False,
         lambda r, t: pm(r, "nimble")["variant_used"] == "B"
         and crit(r, "nimble", "orig", "C2_correct")["state"] == FAIL),
        ("variant_orig_only_fail", O("wrongorig") + ["--variant", "orig"], FAIL, False, None),
        ("wrong_route_C2_fail", C("wrongroute") + K, FAIL, False,
         lambda r, t: crit(r, "jev-latest", "B", "C2_correct")["route_correct"] == 6),
        ("models_judged_separately", O("badmodel") + two, PASS, False,   # one PASS + one FAIL -> exit 0
         lambda r, t: pm(r, "tev1")["verdict"] == PASS and pm(r, "tev1:0.8b")["verdict"] == FAIL
         and "RESULT: PASS (models passing: tev1)" in t and "MODEL VERDICT tev1:0.8b: FAIL (variant=orig; failed=C2)" in t),
        ("urgency_off_by_2_C2_fail", O("urg2"), FAIL, False, None),
        ("C3_case_unit_6of8_fail", O("flip") + ["--stable-unit", "case"], FAIL, False,
         lambda r, t: crit(r, "nimble", "orig", "C3_stable")["state"] == FAIL),
        ("missing_answer_C1_fail", C("missing") + K, FAIL, False, None),
        ("bad_probabilities_C1_fail", O("badprob"), FAIL, False, None),
        ("noul_out_of_range_C1_fail", O("noulrange"), FAIL, False, None),
        ("server_500_C1_fail", C("500") + K, FAIL, False, None),
        ("C6_leak_detected", C("ok") + K, FAIL, True,
         lambda r, t: r["C6_security"]["state"] == FAIL),
        ("config_error_refuses_to_send", O("ok"), FAIL, False, "config"),
        ("auth_403_blocked", C("403") + K, BLOCKED, False, None),
        ("auth_401_echoes_key_blocked", C("401") + K + ["--skip-preflight"], BLOCKED, False, None),
        ("credits_402_blocked", C("402") + K + ["--skip-preflight"], BLOCKED, False, None),
        ("cloud_missing_key_blocked", C("ok"), BLOCKED, False, None),
        ("cloud_empty_keyfile_blocked", C("ok") + ["--key-file", nokey], BLOCKED, False, None),
        ("cloud_insecure_http_blocked", ["--line", "cloud", "--base-url", "http://example.invalid"] + K, BLOCKED, False, None),
        ("ollama_unreachable_blocked", ["--line", "ollama", "--base-url", dead], BLOCKED, False, None),
        ("ollama_old_version_blocked", O("old"), BLOCKED, False, None),
        ("not_pulled_preflight_blocked", O("nopull") + two, BLOCKED, False, None),
        ("not_pulled_404_blocked", O("nopull") + ["--skip-preflight", "--model", "nimble", "--model", "tev1:0.8b"],
         PASS, False, lambda r, t: pm(r, "nimble")["verdict"] == PASS and pm(r, "tev1:0.8b")["verdict"] == BLOCKED
         and "MODEL VERDICT tev1:0.8b: BLOCKED (variant=orig; failed=C1,C2,C3)" in t),
        ("all_models_blocked_exit2", O("nopull") + ["--skip-preflight", "--model", "tev1:0.8b"], BLOCKED, False, None),
        ("one_fail_one_blocked_exit1", O("nopullwrong") + ["--skip-preflight", "--variant", "orig", "--model", "tev1:0.8b",
                                                      "--model", "nimble", "--case", "case1_write_check004"],
         FAIL, False, lambda r, t: pm(r, "nimble")["verdict"] == FAIL and pm(r, "tev1:0.8b")["verdict"] == BLOCKED),
        # ---- set 2 ----
        ("set2_shape_pass", O("ok") + ["--set", "2"], PASS, False,
         lambda r, t: r["set"] == "2" and len(r["case_ids"]) == 20 and r["thresholds"] == {"c1": [18, 20], "c2": [18, 20], "c3": [54, 60]}
         and crit(r, "nimble", "orig", "C1_connect")["requests"] == 60 and crit(r, "nimble", "B", "C3_stable")["pairs_total"] == 60
         and crit(r, "nimble", "B", "C3_stable")["cases_total"] == 20 and crit(r, "nimble", "orig", "C2_correct")["route_correct"] == 20
         and r["question_set_sha256"] == question_set_sha256("2") and ("set=2 question_set_sha256=" + question_set_sha256("2")) in t
         and pm(r, "nimble")["usage_totals"]["input_tokens"] == 300 * 120),
        ("set2_wake_acceptance_section", C("ok") + K + ["--set", "2"], PASS, False,
         lambda r, t: "WAKE-ACCEPTANCE (report only) jev-latest" in t
         and all(set(pm(r, "jev-latest")["wake_acceptance"][v]) == set(SETS["2"]["wake_acceptance"]) for v in VARIANTS)
         and all(x["majority"] == "yes" and x["n"] == 3 and abs(x["mean_noul"] - 0.93) < 1e-9
                 for v in VARIANTS for x in pm(r, "jev-latest")["wake_acceptance"][v].values())),
        ("set2_route_18of20_pass", O("nwrong2") + ["--set", "2"], PASS, False,
         lambda r, t: crit(r, "nimble", "orig", "C2_correct")["route_correct"] == 18
         and crit(r, "nimble", "orig", "C2_correct")["state"] == PASS),
        ("set2_route_17of20_fail", O("nwrong3") + ["--set", "2"], FAIL, False,
         lambda r, t: crit(r, "nimble", "orig", "C2_correct")["route_correct"] == 17
         and "MODEL VERDICT nimble: FAIL (variant=orig; failed=C2)" in t),
        ("set2_C3_54of60_pass", O("nflip6") + ["--set", "2"], PASS, False,
         lambda r, t: crit(r, "nimble", "orig", "C3_stable")["pairs_stable"] == 54
         and crit(r, "nimble", "orig", "C3_stable")["cases_stable"] == 14),
        ("set2_C3_53of60_fail", O("nflip7") + ["--set", "2"], FAIL, False,
         lambda r, t: crit(r, "nimble", "orig", "C3_stable")["pairs_stable"] == 53
         and crit(r, "nimble", "B", "C3_stable")["state"] == FAIL),
        ("set2_unknown_set1_case_config_fail", O("ok") + ["--set", "2", "--case", "case1_write_check004"], FAIL, False,
         "config_case"),
        ("repeats_1_C3_blocked", O("ok") + ["--repeats", "1"], BLOCKED, False, None),
    ]
    saved_env = os.environ.get(KEY_ENV)
    saved_b = ROUTE_INSTRUCTIONS["B"]
    try:
        for name, argv, want, leak, extra in S:
            if name == "cloud_ok_env_key":
                os.environ[KEY_ENV] = fake_key
            else:
                os.environ.pop(KEY_ENV, None)
            if extra == "config":
                ROUTE_INSTRUCTIONS["B"] = "   "     # broken wording must be refused before sending
            for s_ in (srv, srv_o):
                with s_.lock:
                    s_.posts, s_.per_case = 0, {}
            rpt = os.path.join(tmp, name + ".json")
            args = build_parser().parse_args(argv + ["--out", rpt, "--timeout", "10"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = Runner(args, buf, _selftest_inject_leak=leak).run()
            ROUTE_INSTRUCTIONS["B"] = saved_b
            text = buf.getvalue()
            lines = [l for l in text.splitlines() if l.strip()]
            last = lines[-1] if lines else ""
            prefix = "RESULT: PASS (models passing: " if want == PASS else "RESULT: %s (" % want
            rtext = open(rpt, encoding="ascii").read() if os.path.exists(rpt) else ""
            in_stdout, in_report = fake_key in text, fake_key in rtext
            extra_ok = True
            try:
                if extra in ("config", "config_case"):
                    extra_ok = srv_o.posts == 0 and "config error" in last
                    if extra == "config_case":
                        extra_ok = extra_ok and "unknown --case ids" in last and "missing instructions" not in last
                elif extra is not None:
                    extra_ok = bool(extra(json.loads(rtext), text))
                rj = json.loads(rtext) if rtext else {}
                if extra_ok and rj.get("per_model"):
                    # one MODEL VERDICT line per model, matching the report, before RESULT
                    for m, d in rj["per_model"].items():
                        failed = [k for k, v in d["gate"].items() if v != PASS]
                        want_line = "MODEL VERDICT %s: %s (variant=%s; failed=%s)" % (
                            m, d["verdict"], d["variant_used"], ",".join(failed) if failed else "none")
                        if want_line not in lines or lines.index(want_line) > len(lines) - 2:
                            extra_ok = False
            except Exception as e:  # noqa
                extra_ok = False
            try:
                text.encode("ascii")
                is_ascii = True
            except UnicodeEncodeError:
                is_ascii = False
            leak_ok = (in_stdout and not in_report) if leak else (not in_stdout and not in_report)
            ok = code == EXIT_CODES[want] and last.startswith(prefix) and leak_ok and is_ascii and bool(rtext) and extra_ok
            if not ok:
                mismatches.append(name)
                w("---- output of %s (extra_ok=%s) ----\n%s----" % (name, extra_ok, mask(text, Secret(fake_key))))
            w("SELFTEST %-32s want=%-7s exit=%d key_in_stdout=%-3s key_in_report=%-3s %s | %s" % (
                name, want, code, "yes" if in_stdout else "no", "yes" if in_report else "no",
                "ok" if ok else "MISMATCH", mask(last, Secret(fake_key))[:140]))
    finally:
        ROUTE_INSTRUCTIONS["B"] = saved_b
        if saved_env is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = saved_env
        srv.shutdown()
        srv_o.shutdown()
    w("self-test reports in %s" % tmp)
    if mismatches:
        w("RESULT: FAIL (self-test mismatches: %s)" % ", ".join(mismatches))
        return 1
    w("RESULT: PASS (self-test: %d/%d scenarios + 2 unit checks ok)" % (len(S), len(S)))
    return 0

# ==========================================================================
# CLI
# ==========================================================================

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Verify a TypeSafe Jev-style /v1/systemone line (cloud or local Ollama).")
    ap.add_argument("--line", choices=["cloud", "ollama"])
    ap.add_argument("--base-url", help="API root (default cloud %s, ollama %s)" % (CLOUD_DEFAULT_BASE_URL, OLLAMA_DEFAULT_BASE_URL))
    ap.add_argument("--model", action="append",
                    help="repeatable; each model judged separately (default cloud %s, ollama %s)" % (CLOUD_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL))
    ap.add_argument("--key-file", help="one-line key file (cloud). Else env %s. Ollama uses 'ollama' unless given." % KEY_ENV)
    ap.add_argument("--variant", choices=["orig", "B", "both"], default="both",
                    help="route question wording; both = run both, verdict uses the better (default both)")
    ap.add_argument("--set", choices=sorted(SETS), default="1",
                    help="question set: 1 = 8 cases (default), 2 = 20 cases; thresholds scale per set")
    ap.add_argument("--repeats", type=int, default=3, help="runs per case for C3 (default 3)")
    ap.add_argument("--stable-unit", choices=["pair", "case"], default="pair",
                    help="C3 unit: pair (case,question; default) or case (all 3 questions). Both are reported.")
    ap.add_argument("--case", action="append", help="only these case ids of the chosen --set (repeatable); "
                                                    "ids are listed in the JSON report")
    ap.add_argument("--ping", action="store_true", help="also send the Ollama-blog billing ticket once per model (not scored)")
    ap.add_argument("--mem-note", help="local line: free-text memory note for C5 (e.g. 'ollama ps: 9.8 GB')")
    ap.add_argument("--out", default="jev_report.json", help="JSON report path (default jev_report.json)")
    ap.add_argument("--timeout", type=float, default=None, help="per-request seconds (default ollama 120, cloud 30)")
    ap.add_argument("--skip-preflight", action="store_true", help="skip /api/version,/api/tags (ollama) or /v1/models (cloud)")
    ap.add_argument("--dry-run", action="store_true", help="print the payload; send nothing")
    ap.add_argument("--self-test", action="store_true", help="run against an in-process fake server")
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test(sys.stdout)
    if not args.line:
        build_parser().error("--line cloud|ollama is required (or use --self-test)")
    if args.timeout is None:
        args.timeout = 120.0 if args.line == "ollama" else 30.0
    return Runner(args, sys.stdout).run()


if __name__ == "__main__":
    sys.exit(main())
