#!/usr/bin/env python3
"""check_010 - pure decide(snapshot, contract, policy, now) for work order 010.

Written before the workbench implementation. G1-G7 are expected red until
workbench/stop_policy.py, workbench/tests/test_stop_policy.py, and
workbench/fixtures/scenarios.json exist. G8 re-runs check_007 and
check_008 on this same tree and must stay green.

Stdlib only, offline, ASCII stdout. The live tree is read only: G6
appends a decide wrapper on a temp copy. Every child process gets
PYTHONIOENCODING=utf-8 and PYTHONDONTWRITEBYTECODE=1, has leaky
variables such as PYTHONPATH removed, then PYTHONPATH set to workbench.

R4 and R5 are copied below as constants. This script does not read the
spec file while it runs.

Each check prints [PASS], [FAIL], or [BLOCKED]. The process exits 1
if any of them is not PASS. BLOCKED means the check could not be
executed (the interpreter did not start, or the temp copy could not
be made). A product miss is FAIL, including a missing workbench file.
"""

import os
import sys

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

import ast
import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

STOP_REL = "workbench/stop_policy.py"
TEST_REL = "workbench/tests/test_stop_policy.py"
FIXTURE_REL = "workbench/fixtures/scenarios.json"
PRODUCT_RELS = (STOP_REL, TEST_REL, FIXTURE_REL)
MIN_TESTS = 10
SCAN_COMBOS = 5184

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

LEAKY_ENV = (
    "LEDGER_SENTINEL_OUT", "LEDGER_WORK_ORDER_MANIFEST",
    "LEDGER_WORK_ORDER_MANIFEST_SHA256", "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "PYTHONINSPECT", "PYTHONWARNINGS",
)

# G8 hashes every file except these directories. The work order names
# both of them and does not exclude loose bytecode.
HASH_SKIP = {".git", "__pycache__"}
COPY_SKIP = {".git", "__pycache__", ".venv", "venv"}

ALLOWED_IMPORTS = frozenset({
    "copy", "math", "numbers", "typing", "dataclasses", "enum", "types", "collections",
})
BANNED_CALLS = frozenset({
    "open", "print", "input", "eval", "exec", "compile", "__import__", "globals", "setattr",
})
DECIDE_PARAMS = ("snapshot", "contract", "policy", "now")

OUTPUT_KEYS = frozenset({
    "action", "next_state", "reason_code", "ui_message", "data_at_risk",
    "notify_human", "human_hold_after", "stop_intent", "from_unit",
})
EXPECT_KEYS = (
    "action", "next_state", "reason_code", "data_at_risk", "notify_human",
    "human_hold_after", "stop_intent", "from_unit",
)
BOOL_KEYS = frozenset({"data_at_risk", "notify_human", "human_hold_after"})
STR_KEYS = frozenset({"action", "next_state", "reason_code", "stop_intent", "ui_message"})
TOP_KEYS = frozenset({"schema", "base", "scenarios"})
ROW_KEYS = frozenset({"id", "title", "set", "expect"})

# 009 section 2.1 minus the three terminal states DONE, FAILED, CANCELLED.
SCAN_STATES = (
    "REGISTERED", "QUEUED", "STARTING", "RUNNING", "SAVING", "COLLECTING",
    "RELEASING", "RELEASE_UNCONFIRMED", "PAUSED", "RECONCILING", "UNKNOWN", "BLOCKED",
)
SCAN_STATUSES = ("failed", "timeout")
SCAN_FAILURES = (0, 1, 2, 3, 4, 5)
SCAN_MODES = ("A", "B", "C")
# R2 host enum, in listed order. The spec names "three host values".
SCAN_HOSTS = ("online", "shutting_down", "just_booted")
SCAN_FIXED = (
    ("snapshot.human_command", "none"),
    ("snapshot.limit_hit_at", 900),
    ("snapshot.outputs.unsaved", 2),
    ("snapshot.release_check", "check_failed"),
    ("snapshot.remote", "unreachable"),
)
FORBIDDEN_ACTIONS = ("RELEASE", "CLOSE")
FORBIDDEN_NEXT = ("DONE", "FAILED", "PAUSED", "CANCELLED", "RELEASING")

EXPECTED_IDS = (
    "T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T09b",
    "T10a", "T10b", "T11", "T12", "T13", "T14a", "T14b", "T15a", "T15b", "T16",
    "T17a", "T17b", "T18a", "T18b", "T19a", "T19b", "T20", "T21", "U01", "P01",
    "P02", "E01", "E02",
)

URL_RE = re.compile(r"https?://", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A slash path not glued to an identifier, so `a/b` division is not a path.
UNIX_ABS_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_./])(/(?:[A-Za-z0-9._\-]+)+(?:/(?:[A-Za-z0-9._\-]+)*)*)"
)
DRIVE_RE = re.compile(r"(?:^|[^A-Za-z0-9_])([A-Za-z]:[\\/][^\s\"'`]*)")
TOKEN_RES = (
    ("github token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("key token", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws token", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("assigned secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|refresh[_-]?token|password)\b"
        r"\s*[:=]\s*['\"][^'\"]{6,}['\"]"
    )),
    ("bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
)

RAN_RE = re.compile(r"^Ran (\d+) tests?\b", re.MULTILINE)

# Wrappers are appended. They do not read the original function body.
M1_SRC = """\
_check010_orig_decide = decide


def decide(snapshot, contract, policy, now):
    probe = snapshot.get("probe") if isinstance(snapshot, dict) else None
    status = probe.get("status") if isinstance(probe, dict) else None
    command = snapshot.get("human_command") if isinstance(snapshot, dict) else None
    if status != "ok" and command == "none":
        return {
            "action": "RELEASE",
            "next_state": "RELEASING",
            "reason_code": "PROBE_FAIL_AS_IDLE",
            "ui_message": "mutant",
            "data_at_risk": False,
            "notify_human": False,
            "human_hold_after": False,
            "stop_intent": "none",
            "from_unit": None,
        }
    return _check010_orig_decide(snapshot, contract, policy, now)
"""

M2_SRC = """\
_check010_orig_decide = decide


def decide(snapshot, contract, policy, now):
    chosen = snapshot
    if isinstance(snapshot, dict):
        request = snapshot.get("bot_request")
        if request not in (None, "none") and snapshot.get("human_hold") is True:
            chosen = dict(snapshot)
            chosen["human_hold"] = False
    return _check010_orig_decide(chosen, contract, policy, now)
"""

M3_SRC = """\
_check010_orig_decide = decide


def decide(snapshot, contract, policy, now):
    chosen = policy
    if isinstance(policy, dict) and policy.get("budget_conflict_mode") == "C":
        chosen = dict(policy)
        chosen["budget_conflict_mode"] = "A"
    return _check010_orig_decide(snapshot, contract, chosen, now)
"""

MUTANTS = (
    ("M1", M1_SRC),
    ("M2", M2_SRC),
    ("M3", M3_SRC),
)

# R4 base and R5 rows, copied from the spec. Not parsed from the spec at runtime.
TABLE_JSON = r"""
{
  "base": {
    "now": 1000,
    "snapshot": {
      "state": "RUNNING",
      "probe": {
        "status": "ok",
        "consecutive_failures": 0
      },
      "progress": {
        "value": 120,
        "last_advanced_at": 999
      },
      "checkpoint": {
        "step": 120,
        "confirmed": true,
        "confirmed_at": 990
      },
      "outputs": {
        "unsaved": 0,
        "pending_download": 0,
        "first_unverified": null,
        "sha_mismatch": 0,
        "download_retries_used": 0
      },
      "cu_used": 5,
      "elapsed_minutes": 60,
      "limit_hit_at": null,
      "unknown_since": null,
      "human_command": "none",
      "bot_request": "none",
      "human_hold": false,
      "stop_intent": "none",
      "host": "online",
      "remote": "running",
      "release_check": "not_started",
      "release_retries_used": 0,
      "done_signal": false,
      "queue_empty": false
    },
    "contract": {
      "job_id": "demo-J3-001",
      "template_id": "tpl-demo-train",
      "job_type": "J3",
      "workload_kind": "training",
      "cu_cap": 10,
      "cu_soft_ratio": 0.8,
      "max_minutes": 120,
      "heartbeat": {
        "stall_minutes": 20
      },
      "on_host_offline": "pause_safely",
      "submitted_by": "human"
    },
    "policy": {
      "probe_confirm_count": 3,
      "unknown_alert_minutes": 30,
      "budget_conflict_mode": "C",
      "grace_cu_ratio": 0.1,
      "grace_minutes": 15,
      "save_before_max_minutes": 10,
      "download_retry_limit": 3,
      "release_recheck_limit": 3
    }
  },
  "scenarios": [
    {
      "id": "T01",
      "raises": false,
      "set": {
        "snapshot.probe.status": "failed",
        "snapshot.probe.consecutive_failures": 1
      },
      "expect": {
        "action": "WAIT",
        "next_state": "RUNNING",
        "reason_code": "PROBE_RETRY",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T02",
      "raises": false,
      "set": {
        "snapshot.probe.status": "timeout",
        "snapshot.probe.consecutive_failures": 3
      },
      "expect": {
        "action": "MARK_UNKNOWN",
        "next_state": "UNKNOWN",
        "reason_code": "PROBE_UNCERTAIN",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T03",
      "raises": false,
      "set": {
        "snapshot.state": "UNKNOWN",
        "snapshot.probe.status": "failed",
        "snapshot.probe.consecutive_failures": 5,
        "snapshot.unknown_since": 960
      },
      "expect": {
        "action": "ESCALATE",
        "next_state": "BLOCKED",
        "reason_code": "UNKNOWN_TOO_LONG",
        "data_at_risk": false,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T04",
      "raises": false,
      "set": {
        "snapshot.progress.last_advanced_at": 975
      },
      "expect": {
        "action": "COLLECT",
        "next_state": "COLLECTING",
        "reason_code": "STALLED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "fail",
        "from_unit": null
      }
    },
    {
      "id": "T05",
      "raises": false,
      "set": {
        "snapshot.progress.last_advanced_at": 1000
      },
      "expect": {
        "action": "CONTINUE",
        "next_state": "RUNNING",
        "reason_code": "OK",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T06",
      "raises": false,
      "set": {
        "snapshot.cu_used": 8
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "CU_SOFT_CAP",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T07",
      "raises": false,
      "set": {
        "snapshot.cu_used": 10,
        "snapshot.limit_hit_at": 1000
      },
      "expect": {
        "action": "COLLECT",
        "next_state": "COLLECTING",
        "reason_code": "CU_HARD_CAP",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T08",
      "raises": false,
      "set": {
        "snapshot.cu_used": 10.5,
        "snapshot.limit_hit_at": 995,
        "snapshot.outputs.unsaved": 2
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "CU_HARD_CAP_UNSAVED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T09",
      "raises": false,
      "set": {
        "snapshot.cu_used": 11.1,
        "snapshot.limit_hit_at": 995,
        "snapshot.outputs.unsaved": 2
      },
      "expect": {
        "action": "RELEASE",
        "next_state": "RELEASING",
        "reason_code": "CU_GRACE_EXHAUSTED",
        "data_at_risk": true,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T09b",
      "raises": false,
      "set": {
        "snapshot.cu_used": 10.2,
        "snapshot.limit_hit_at": 985,
        "snapshot.outputs.unsaved": 2
      },
      "expect": {
        "action": "RELEASE",
        "next_state": "RELEASING",
        "reason_code": "CU_GRACE_EXHAUSTED",
        "data_at_risk": true,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T10a",
      "raises": false,
      "set": {
        "snapshot.cu_used": 10.5,
        "snapshot.limit_hit_at": 995,
        "snapshot.outputs.unsaved": 2,
        "policy.budget_conflict_mode": "A"
      },
      "expect": {
        "action": "RELEASE",
        "next_state": "RELEASING",
        "reason_code": "CU_HARD_CAP_UNSAVED",
        "data_at_risk": true,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T10b",
      "raises": false,
      "set": {
        "snapshot.cu_used": 11.1,
        "snapshot.limit_hit_at": 985,
        "snapshot.outputs.unsaved": 2,
        "policy.budget_conflict_mode": "B"
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "CU_HARD_CAP_UNSAVED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T11",
      "raises": false,
      "set": {
        "contract.submitted_by": "bot:demo",
        "snapshot.human_command": "stop_after_save"
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "HUMAN_STOP",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": true,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T12",
      "raises": false,
      "set": {
        "contract.submitted_by": "bot:demo",
        "snapshot.state": "PAUSED",
        "snapshot.human_hold": true,
        "snapshot.bot_request": "resume"
      },
      "expect": {
        "action": "REJECT_REQUEST",
        "next_state": "PAUSED",
        "reason_code": "HUMAN_HOLD",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": true,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T13",
      "raises": false,
      "set": {
        "snapshot.human_command": "stop_now",
        "snapshot.outputs.unsaved": 1
      },
      "expect": {
        "action": "RELEASE",
        "next_state": "RELEASING",
        "reason_code": "HUMAN_STOP",
        "data_at_risk": true,
        "notify_human": false,
        "human_hold_after": true,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T14a",
      "raises": false,
      "set": {
        "snapshot.host": "shutting_down"
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "HOST_SHUTDOWN",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "T14b",
      "raises": false,
      "set": {
        "snapshot.host": "shutting_down",
        "snapshot.state": "RELEASING",
        "snapshot.release_check": "confirmed_zero",
        "snapshot.stop_intent": "pause"
      },
      "expect": {
        "action": "CLOSE",
        "next_state": "PAUSED",
        "reason_code": "RELEASE_CONFIRMED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T15a",
      "raises": false,
      "set": {
        "snapshot.host": "just_booted"
      },
      "expect": {
        "action": "RECONCILE",
        "next_state": "RECONCILING",
        "reason_code": "BOOT_RECONCILE",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T15b",
      "raises": false,
      "set": {
        "snapshot.host": "just_booted",
        "snapshot.state": "RECONCILING",
        "snapshot.remote": "released",
        "snapshot.progress.value": 300,
        "snapshot.checkpoint.step": 300
      },
      "expect": {
        "action": "CLOSE",
        "next_state": "PAUSED",
        "reason_code": "RECONCILED_PAUSED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": 300
      }
    },
    {
      "id": "T16",
      "raises": false,
      "set": {
        "snapshot.host": "just_booted",
        "snapshot.state": "RECONCILING",
        "snapshot.remote": "unreachable",
        "snapshot.probe.status": "failed",
        "snapshot.probe.consecutive_failures": 1
      },
      "expect": {
        "action": "MARK_UNKNOWN",
        "next_state": "UNKNOWN",
        "reason_code": "PROBE_UNCERTAIN",
        "data_at_risk": false,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T17a",
      "raises": false,
      "set": {
        "contract.workload_kind": "batch_inference",
        "contract.job_type": "J1",
        "snapshot.state": "RECONCILING",
        "snapshot.remote": "finished",
        "snapshot.outputs.pending_download": 3,
        "snapshot.outputs.first_unverified": 23
      },
      "expect": {
        "action": "COLLECT",
        "next_state": "COLLECTING",
        "reason_code": "RECONCILED_COLLECT",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": 23
      }
    },
    {
      "id": "T17b",
      "raises": false,
      "set": {
        "contract.workload_kind": "batch_inference",
        "contract.job_type": "J1",
        "snapshot.state": "RECONCILING",
        "snapshot.remote": "released",
        "snapshot.outputs.pending_download": 3,
        "snapshot.outputs.first_unverified": 23
      },
      "expect": {
        "action": "CLOSE",
        "next_state": "PAUSED",
        "reason_code": "RECONCILED_PAUSED",
        "data_at_risk": true,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": 23
      }
    },
    {
      "id": "T18a",
      "raises": false,
      "set": {
        "snapshot.state": "COLLECTING",
        "snapshot.outputs.sha_mismatch": 1,
        "snapshot.outputs.download_retries_used": 1
      },
      "expect": {
        "action": "COLLECT",
        "next_state": "COLLECTING",
        "reason_code": "SHA_MISMATCH",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T18b",
      "raises": false,
      "set": {
        "snapshot.state": "COLLECTING",
        "snapshot.outputs.sha_mismatch": 1,
        "snapshot.outputs.download_retries_used": 3
      },
      "expect": {
        "action": "ESCALATE",
        "next_state": "BLOCKED",
        "reason_code": "SHA_MISMATCH",
        "data_at_risk": false,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T19a",
      "raises": false,
      "set": {
        "snapshot.state": "RELEASING",
        "snapshot.release_check": "active_nonzero",
        "snapshot.stop_intent": "finish"
      },
      "expect": {
        "action": "RECHECK_RELEASE",
        "next_state": "RELEASE_UNCONFIRMED",
        "reason_code": "RELEASE_NOT_CONFIRMED",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "finish",
        "from_unit": null
      }
    },
    {
      "id": "T19b",
      "raises": false,
      "set": {
        "snapshot.state": "RELEASE_UNCONFIRMED",
        "snapshot.release_check": "check_failed",
        "snapshot.release_retries_used": 3,
        "snapshot.stop_intent": "finish"
      },
      "expect": {
        "action": "ESCALATE",
        "next_state": "RELEASE_UNCONFIRMED",
        "reason_code": "RELEASE_NOT_CONFIRMED",
        "data_at_risk": false,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "finish",
        "from_unit": null
      }
    },
    {
      "id": "T20",
      "raises": false,
      "set": {
        "snapshot.queue_empty": true
      },
      "expect": {
        "action": "CONTINUE",
        "next_state": "RUNNING",
        "reason_code": "OK",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "T21",
      "raises": false,
      "set": {
        "snapshot.elapsed_minutes": 120,
        "snapshot.checkpoint.confirmed_at": 998
      },
      "expect": {
        "action": "COLLECT",
        "next_state": "COLLECTING",
        "reason_code": "MAX_TIME",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "U01",
      "raises": false,
      "set": {
        "snapshot.state": "UNKNOWN",
        "snapshot.probe.status": "failed",
        "snapshot.probe.consecutive_failures": 4,
        "snapshot.unknown_since": 995,
        "snapshot.cu_used": 11.1,
        "snapshot.limit_hit_at": 990
      },
      "expect": {
        "action": "ESCALATE",
        "next_state": "BLOCKED",
        "reason_code": "CU_HARD_CAP_UNKNOWN",
        "data_at_risk": false,
        "notify_human": true,
        "human_hold_after": false,
        "stop_intent": "none",
        "from_unit": null
      }
    },
    {
      "id": "P01",
      "raises": false,
      "set": {
        "snapshot.bot_request": "pause"
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "BOT_PAUSE",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": false,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "P02",
      "raises": false,
      "set": {
        "contract.submitted_by": "bot:demo",
        "snapshot.human_command": "stop_after_save",
        "snapshot.bot_request": "resume"
      },
      "expect": {
        "action": "REQUEST_SAVE",
        "next_state": "SAVING",
        "reason_code": "HUMAN_STOP",
        "data_at_risk": false,
        "notify_human": false,
        "human_hold_after": true,
        "stop_intent": "pause",
        "from_unit": null
      }
    },
    {
      "id": "E01",
      "raises": true,
      "set": {
        "snapshot.state": "IDLE"
      },
      "expect": null
    },
    {
      "id": "E02",
      "raises": true,
      "set": {
        "policy.budget_conflict_mode": "D"
      },
      "expect": null
    }
  ]
}
"""

FAILURES = []
BASE = None
SCENARIOS = None
TABLE_ERROR = ""
CU_11_1 = json.loads("11.1")
SCAN_CU = (5, 10, CU_11_1, 50)


def load_table(text):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("table is not an object")
    base = data["base"]
    scenarios = data["scenarios"]
    if not isinstance(base, dict) or not isinstance(scenarios, list):
        raise ValueError("table shape")
    for key in ("now", "snapshot", "contract", "policy"):
        if key not in base:
            raise ValueError("table base missing " + key)
    ids = []
    for row in scenarios:
        if not isinstance(row, dict):
            raise ValueError("table row")
        ids.append(row.get("id"))
        if row.get("raises"):
            if row.get("expect") is not None:
                raise ValueError("raise row has expect")
        else:
            expect = row.get("expect")
            if not isinstance(expect, dict) or set(expect) != set(EXPECT_KEYS):
                raise ValueError("expect keys")
            updates = row.get("set")
            if not isinstance(updates, dict):
                raise ValueError("set shape")
    if ids != list(EXPECTED_IDS):
        raise ValueError("table ids")
    return base, scenarios


try:
    BASE, SCENARIOS = load_table(TABLE_JSON)
except (TypeError, ValueError, KeyError) as exc:
    TABLE_ERROR = type(exc).__name__ + ": " + str(exc)


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
    then set to the literal workbench so imports follow the child's cwd.
    """
    env = dict(os.environ)
    for key in LEAKY_ENV:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "workbench"
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


def tail(proc, n=200):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return text[-n:]


def could_not_start(proc):
    return proc.returncode in (124, 127)


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def missing_rels(rels):
    missing = []
    for rel in rels:
        if not (REPO_ROOT / rel).is_file():
            missing.append(rel)
    return missing


def ran_count(text):
    found = RAN_RE.findall(text or "")
    if not found:
        return None
    return int(found[-1])


def result_line(text):
    lines = [line for line in text.splitlines() if line.startswith("RESULT:")]
    return lines[-1] if lines else ""


def unittest_argv():
    return [sys.executable, "-m", "unittest", "discover", "-s", "workbench/tests"]


def run_unittest(root):
    return run_process(unittest_argv(), root, timeout=60)


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


def join_bits(parts, limit=6):
    if len(parts) <= limit:
        return "; ".join(parts)
    head = "; ".join(parts[:limit])
    return head + "; +" + str(len(parts) - limit) + " more"


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("non-string key")
        if key in obj:
            raise ValueError("duplicate key " + key)
        obj[key] = value
    return obj


def loads_strict(text):
    return json.loads(text, object_pairs_hook=strict_object)


def parse_probe_stdout(text):
    body = text[:-1] if text.endswith("\n") else text
    if body.endswith("\r"):
        body = body[:-1]
    if body == "" or "\n" in body or "\r" in body:
        return None, "probe stdout is not one JSON line"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, "probe stdout is not JSON"
    if not isinstance(payload, dict):
        return None, "probe JSON is not an object"
    return payload, ""


def apply_set(base, updates):
    root = copy.deepcopy(base)
    for path, value in updates.items():
        parts = path.split(".")
        if len(parts) < 2 or parts[0] not in ("snapshot", "contract", "policy"):
            raise ValueError("bad path " + path)
        node = root
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise ValueError("missing path " + path)
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise ValueError("missing path " + path)
        node[parts[-1]] = copy.deepcopy(value)
    return root


def table_ready():
    if TABLE_ERROR:
        return "internal table " + TABLE_ERROR
    if not isinstance(BASE, dict) or not isinstance(SCENARIOS, list):
        return "internal table is empty"
    return ""


# ---------------------------------------------------------------- driver
# The probe program lives outside the repo. argv is cleared before
# stop_policy is imported so the product does not see the payload path.
DRIVER = r"""
import copy
import json
import sys

payload_path = sys.argv[1]
sys.argv = ["decide-probe"]
import stop_policy


def apply_updates(snapshot, contract, policy, updates):
    for path, value in updates:
        head, dot, rest = path.partition(".")
        if dot != "." or rest == "":
            raise KeyError(path)
        if head == "snapshot":
            node = snapshot
        elif head == "contract":
            node = contract
        elif head == "policy":
            node = policy
        else:
            raise KeyError(path)
        parts = rest.split(".")
        for part in parts[:-1]:
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            raise KeyError(path)
        node[parts[-1]] = value


def outcome(snapshot, contract, policy, now):
    snap = copy.deepcopy(snapshot)
    cont = copy.deepcopy(contract)
    pol = copy.deepcopy(policy)
    before = (copy.deepcopy(snap), copy.deepcopy(cont), copy.deepcopy(pol))
    try:
        got = stop_policy.decide(snap, cont, pol, now)
    except Exception as exc:
        return {
            "exc": type(exc).__name__,
            "exact_valueerror": type(exc) is ValueError,
            "mutated": (snap, cont, pol) != before,
            "is_dict": False,
            "value": None,
        }
    mutated = (snap, cont, pol) != before
    if not isinstance(got, dict):
        return {
            "exc": None,
            "exact_valueerror": False,
            "mutated": mutated,
            "is_dict": False,
            "value": None,
        }
    try:
        json.dumps(got, ensure_ascii=True)
    except (TypeError, ValueError):
        return {
            "exc": None,
            "exact_valueerror": False,
            "mutated": mutated,
            "is_dict": True,
            "value": None,
            "unserializable": True,
        }
    return {
        "exc": None,
        "exact_valueerror": False,
        "mutated": mutated,
        "is_dict": True,
        "value": got,
    }


def same_outcome(left, right):
    return left.get("exc") == right.get("exc") and left.get("value") == right.get("value")


def run_cases(req):
    results = []
    for case in req["cases"]:
        first = outcome(case["snapshot"], case["contract"], case["policy"], case["now"])
        second = outcome(case["snapshot"], case["contract"], case["policy"], case["now"])
        results.append({
            "id": case["id"],
            "first": first,
            "second": second,
            "same": same_outcome(first, second),
        })
    return {"results": results}


def run_scan(req):
    base = req["base"]
    forbidden_action = set(req["forbidden_action"])
    forbidden_next = set(req["forbidden_next"])
    count = 0
    violations = 0
    samples = []
    for state in req["states"]:
        for status in req["statuses"]:
            for failures in req["failures"]:
                for cu_used in req["cu"]:
                    for mode in req["modes"]:
                        for host in req["hosts"]:
                            count += 1
                            updates = list(req["fixed"])
                            updates.extend((
                                ("snapshot.state", state),
                                ("snapshot.probe.status", status),
                                ("snapshot.probe.consecutive_failures", failures),
                                ("snapshot.cu_used", cu_used),
                                ("policy.budget_conflict_mode", mode),
                                ("snapshot.host", host),
                            ))
                            snap = copy.deepcopy(base["snapshot"])
                            cont = copy.deepcopy(base["contract"])
                            pol = copy.deepcopy(base["policy"])
                            apply_updates(snap, cont, pol, updates)
                            result = outcome(snap, cont, pol, base["now"])
                            problem = None
                            if result.get("mutated"):
                                problem = "mutated input"
                            elif result.get("exc") is not None:
                                problem = "raised " + str(result.get("exc"))
                            elif not result.get("is_dict") or result.get("value") is None:
                                problem = "not a dict"
                            else:
                                action = result["value"].get("action")
                                nxt = result["value"].get("next_state")
                                if action in forbidden_action:
                                    problem = "action " + ascii_safe(action)
                                elif nxt in forbidden_next and nxt != state:
                                    problem = "next " + ascii_safe(nxt)
                            if problem:
                                violations += 1
                                if len(samples) < 5:
                                    samples.append(
                                        str(state) + " " + str(status)
                                        + " fail=" + str(failures)
                                        + " cu=" + str(cu_used)
                                        + " mode=" + str(mode)
                                        + " host=" + str(host)
                                        + " " + problem
                                    )
    return {"count": count, "violations": violations, "samples": samples}


def ascii_safe(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def main():
    req = json.loads(open(payload_path, encoding="utf-8").read())
    mode = req.get("mode")
    if mode == "cases":
        payload = run_cases(req)
    elif mode == "scan":
        payload = run_scan(req)
    else:
        raise ValueError("bad mode")
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + ": " + str(exc) + "\n")
        raise SystemExit(1)
"""


def launch_driver(payload, timeout):
    try:
        compile(DRIVER, "<check010-driver>", "exec")
    except SyntaxError as exc:
        return None, "driver does not compile: " + str(exc)
    parent = outside_temp_parent()
    if parent is None:
        return None, "no directory outside the repo"
    try:
        holder = tempfile.TemporaryDirectory(prefix="check010-probe-", dir=str(parent))
    except OSError as exc:
        return None, type(exc).__name__
    with holder:
        script_path = Path(holder.name) / "driver.py"
        payload_path = Path(holder.name) / "payload.json"
        try:
            root = REPO_ROOT.resolve()
            if script_path.resolve().is_relative_to(root):
                return None, "probe landed in the live tree"
            text = DRIVER if DRIVER.endswith("\n") else DRIVER + "\n"
            script_path.write_text(text, encoding="utf-8", newline="\n")
            payload_path.write_text(
                json.dumps(payload, ensure_ascii=True),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            return None, type(exc).__name__
        proc = run_process(
            [sys.executable, str(script_path), str(payload_path)],
            REPO_ROOT,
            timeout=timeout,
        )
        return proc, ""


def probe_failure(proc, err, label):
    if proc is None:
        if err and err.startswith("driver"):
            return FAIL, err
        return BLOCKED, label + " " + (err or "did not start")
    if could_not_start(proc):
        return BLOCKED, label + " could not start rc=" + str(proc.returncode) + " tail=" + one_line(tail(proc))
    if proc.returncode != 0:
        return FAIL, label + " exit " + str(proc.returncode) + " tail=" + one_line(tail(proc))
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


def import_problems(tree):
    problems = []
    seen = set()
    for module, relative in iter_imports(tree):
        if relative:
            issue = "relative import " + (module or ".")
        else:
            top = (module or "").split(".", 1)[0]
            if top not in ALLOWED_IMPORTS:
                issue = "import " + (top or "?")
            else:
                issue = None
        if issue and issue not in seen:
            seen.add(issue)
            problems.append(issue)
    return problems


def call_problems(tree):
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            name = None
        if name in BANNED_CALLS and name not in seen:
            seen.add(name)
            found.append("calls " + name)
    return found


def signature_problems(tree):
    fns = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "decide"
    ]
    asyncs = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "decide"
    ]
    problems = []
    if asyncs:
        problems.append("decide is async")
    if len(fns) != 1:
        problems.append("top-level decide count " + str(len(fns)))
        return problems
    args = fns[0].args
    positional = list(args.posonlyargs) + list(args.args)
    names = [item.arg for item in positional]
    if tuple(names) != DECIDE_PARAMS:
        shown = ",".join(names) if names else "none"
        problems.append("parameters " + shown)
    has_default = bool(args.defaults) or any(item is not None for item in args.kw_defaults)
    if has_default:
        problems.append("has a default")
    if args.vararg is not None:
        problems.append("has *args")
    if args.kwarg is not None:
        problems.append("has **kwargs")
    if args.kwonlyargs:
        problems.append("has keyword-only parameters")
    return problems


def g1_shape():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    path = REPO_ROOT / STOP_REL
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError as exc:
        return FAIL, "stop_policy.py does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return FAIL, "stop_policy.py unreadable: " + type(exc).__name__
    problems = []
    problems.extend(signature_problems(tree))
    problems.extend(import_problems(tree))
    problems.extend(call_problems(tree))
    proc = run_process(
        [sys.executable, "-c", "import stop_policy"], REPO_ROOT, timeout=30)
    if could_not_start(proc):
        note = "import stop_policy could not start rc=" + str(proc.returncode)
        if problems:
            return FAIL, "; ".join(problems) + "; " + note
        return BLOCKED, note + " tail=" + one_line(tail(proc))
    if proc.returncode != 0:
        problems.append("import stop_policy exit " + str(proc.returncode))
    if (proc.stdout or "") != "":
        problems.append("import stop_policy stdout not empty")
    if (proc.stderr or "") != "":
        problems.append("import stop_policy stderr not empty")
    if problems:
        detail = "; ".join(problems)
        if proc.returncode != 0 or (proc.stdout or "") or (proc.stderr or ""):
            detail += " tail=" + one_line(tail(proc))
        return FAIL, detail
    return PASS, "import_stdout_empty=True import_stderr_empty=True"


# ---------------------------------------------------------------- G2
def fixture_problems(doc):
    problems = []
    if set(doc) != TOP_KEYS:
        problems.append("top-level keys " + ",".join(sorted(str(key) for key in doc)))
        return problems
    schema = doc.get("schema")
    if type(schema) is not int or schema != 1:
        problems.append("schema " + repr(schema))
    if doc.get("base") != BASE:
        problems.append("base != R4")
    rows = doc.get("scenarios")
    if not isinstance(rows, list):
        problems.append("scenarios is not a list")
        return problems
    if len(rows) != len(SCENARIOS):
        problems.append("scenario count " + str(len(rows)))
    for index, (row, expect_row) in enumerate(zip(rows, SCENARIOS)):
        label = str(expect_row["id"])
        if not isinstance(row, dict):
            problems.append(label + " is not an object")
            continue
        if set(row) != ROW_KEYS:
            problems.append(label + " keys")
            continue
        if row.get("id") != label or not isinstance(row.get("id"), str):
            problems.append("index " + str(index) + " id " + repr(row.get("id")))
            continue
        if not isinstance(row.get("title"), str):
            problems.append(label + " title is not a string")
        if row.get("set") != expect_row["set"]:
            problems.append(label + " set")
        got = row.get("expect")
        if expect_row["raises"]:
            if got != {"raises": "ValueError"}:
                problems.append(label + " expect")
        else:
            wanted = expect_row["expect"]
            if (not isinstance(got, dict) or set(got) != set(EXPECT_KEYS)
                    or any(got.get(key) != wanted[key] for key in EXPECT_KEYS)):
                problems.append(label + " expect")
    if isinstance(rows, list) and len(rows) > len(SCENARIOS):
        problems.append("extra scenarios " + str(len(rows) - len(SCENARIOS)))
    return problems


def g2_fixture():
    problem = table_ready()
    if problem:
        return FAIL, problem
    path = REPO_ROOT / FIXTURE_REL
    if not path.is_file():
        return FAIL, "missing " + FIXTURE_REL
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return FAIL, "scenarios.json unreadable: " + type(exc).__name__
    try:
        doc = loads_strict(text)
    except ValueError as exc:
        message = str(exc)
        if "duplicate key" in message:
            return FAIL, message
        return FAIL, "scenarios.json is not strict JSON: " + type(exc).__name__
    if not isinstance(doc, dict):
        return FAIL, "scenarios.json is not an object"
    problems = fixture_problems(doc)
    if problems:
        return FAIL, join_bits(problems)
    return PASS, "rows=" + str(len(SCENARIOS)) + " base=equal"


# ---------------------------------------------------------------- G3
def value_ok(key, got, expect):
    if got != expect:
        return False
    if key in BOOL_KEYS:
        return type(got) is bool
    if key in STR_KEYS:
        return isinstance(got, str)
    if key == "from_unit":
        if expect is None:
            return got is None
        return type(got) is int
    return True


def case_problems(row, result):
    if not isinstance(result, dict):
        return ["result missing"]
    first = result.get("first")
    second = result.get("second")
    if not isinstance(first, dict) or not isinstance(second, dict):
        return ["result shape"]
    problems = []
    if first.get("mutated") or second.get("mutated"):
        problems.append("mutated input")
    if row["raises"]:
        if not (first.get("exact_valueerror") and second.get("exact_valueerror")):
            problems.append(
                "exc " + repr(first.get("exc")) + "/" + repr(second.get("exc"))
            )
        elif not result.get("same"):
            problems.append("two calls differ")
        return problems
    if not result.get("same"):
        problems.append("two calls differ")
    if first.get("exc") is not None:
        problems.append("raised " + str(first.get("exc")))
        return problems
    if first.get("unserializable"):
        problems.append("return is not JSON")
        return problems
    if not first.get("is_dict") or not isinstance(first.get("value"), dict):
        problems.append("return is not a dict")
        return problems
    value = first["value"]
    if set(value) != OUTPUT_KEYS:
        problems.append("keys " + ",".join(sorted(str(key) for key in value)))
        return problems
    for key in EXPECT_KEYS:
        if not value_ok(key, value.get(key), row["expect"][key]):
            problems.append(key + "=" + repr(value.get(key)))
    ui = value.get("ui_message")
    if not isinstance(ui, str) or ui == "":
        problems.append("ui_message empty")
    return problems


def g3_behavior():
    problem = table_ready()
    if problem:
        return FAIL, problem
    if not (REPO_ROOT / STOP_REL).is_file():
        return FAIL, "missing " + STOP_REL
    cases = []
    for row in SCENARIOS:
        built = apply_set(BASE, row["set"])
        cases.append({
            "id": row["id"],
            "snapshot": built["snapshot"],
            "contract": built["contract"],
            "policy": built["policy"],
            "now": built["now"],
        })
    proc, err = launch_driver({"mode": "cases", "cases": cases}, 60)
    failed = probe_failure(proc, err, "behavior probe")
    if failed:
        return failed
    payload, parse_problem = parse_probe_stdout(proc.stdout or "")
    if parse_problem:
        return FAIL, parse_problem
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(SCENARIOS):
        got = len(results) if isinstance(results, list) else "none"
        return FAIL, "behavior probe result count " + str(got)
    mismatches = []
    for row, result in zip(SCENARIOS, results):
        if not isinstance(result, dict) or result.get("id") != row["id"]:
            mismatches.append(str(row["id"]) + " id")
            continue
        bits = case_problems(row, result)
        if bits:
            mismatches.append(str(row["id"]) + " " + ", ".join(bits))
    if mismatches:
        return FAIL, join_bits(mismatches)
    return PASS, "rows=" + str(len(SCENARIOS)) + " unchanged=True stable=True"


# ---------------------------------------------------------------- G4
def g4_scan():
    problem = table_ready()
    if problem:
        return FAIL, problem
    if not (REPO_ROOT / STOP_REL).is_file():
        return FAIL, "missing " + STOP_REL
    expected = (
        len(SCAN_STATES) * len(SCAN_STATUSES) * len(SCAN_FAILURES)
        * len(SCAN_CU) * len(SCAN_MODES) * len(SCAN_HOSTS)
    )
    if expected != SCAN_COMBOS:
        return FAIL, "internal scan size " + str(expected)
    payload = {
        "mode": "scan",
        "base": BASE,
        "states": list(SCAN_STATES),
        "statuses": list(SCAN_STATUSES),
        "failures": list(SCAN_FAILURES),
        "cu": list(SCAN_CU),
        "modes": list(SCAN_MODES),
        "hosts": list(SCAN_HOSTS),
        "fixed": [list(item) for item in SCAN_FIXED],
        "forbidden_action": list(FORBIDDEN_ACTIONS),
        "forbidden_next": list(FORBIDDEN_NEXT),
    }
    proc, err = launch_driver(payload, 60)
    failed = probe_failure(proc, err, "scan probe")
    if failed:
        return failed
    payload, parse_problem = parse_probe_stdout(proc.stdout or "")
    if parse_problem:
        return FAIL, parse_problem
    count = payload.get("count")
    violations = payload.get("violations")
    samples = payload.get("samples")
    if count != SCAN_COMBOS or not isinstance(violations, int):
        return FAIL, "scan count " + repr(count)
    if violations:
        shown = samples if isinstance(samples, list) else []
        detail = "violations=" + str(violations) + "/" + str(count)
        if shown:
            detail += " " + "; ".join(str(item) for item in shown)
        return FAIL, detail
    return PASS, "combos=" + str(count) + " violations=0"


# ---------------------------------------------------------------- G5
def g5_tests():
    missing = missing_rels(PRODUCT_RELS)
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


# ---------------------------------------------------------------- G6
def append_mutant(source, wrapper):
    text = source
    if not text.endswith("\n"):
        text += "\n"
    rewritten = text + "\n" + wrapper
    if not rewritten.endswith("\n"):
        rewritten += "\n"
    compile(rewritten, "<g6-mutant>", "exec")
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


def g6_in_copy(parent, source):
    pack = Path(parent) / "repo"
    try:
        shutil.copytree(REPO_ROOT, pack, ignore=ignore_noise)
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__
    dest = pack / STOP_REL
    root = REPO_ROOT.resolve()
    try:
        aliased = dest.resolve().is_relative_to(root)
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__
    if aliased:
        return FAIL, "temp copy aliased the live tree"
    parts = []
    miss = False
    blocked = False
    for name, wrapper in MUTANTS:
        try:
            rewritten = append_mutant(source, wrapper)
        except (SyntaxError, ValueError) as exc:
            return FAIL, name + " could not be installed: " + type(exc).__name__
        try:
            if dest.resolve().is_relative_to(root):
                return FAIL, "temp copy aliased the live tree"
            dest.write_text(rewritten, encoding="utf-8", newline="\n")
            if dest.resolve().is_relative_to(root):
                return FAIL, "mutant write landed in the live tree"
        except OSError as exc:
            return BLOCKED, "mutant write failed: " + type(exc).__name__
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


def g6_mutants():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    path = REPO_ROOT / STOP_REL
    try:
        source = read_text(path)
        ast.parse(source)
    except SyntaxError as exc:
        return FAIL, "stop_policy.py does not parse: " + str(exc)
    except (OSError, UnicodeError) as exc:
        return FAIL, "stop_policy.py unreadable: " + type(exc).__name__
    live = run_unittest(REPO_ROOT)
    if could_not_start(live):
        return BLOCKED, "live tests could not start rc=" + str(live.returncode)
    if live.returncode != 0:
        return FAIL, (
            "tests are not green before mutation exit="
            + str(live.returncode) + " tail=" + one_line(tail(live))
        )
    parent = outside_temp_parent()
    if parent is None:
        return BLOCKED, "temp copy failed: no directory outside the repo"
    try:
        holder = tempfile.TemporaryDirectory(prefix="check010-", dir=str(parent))
    except OSError as exc:
        return BLOCKED, "temp copy failed: " + type(exc).__name__
    with holder:
        return g6_in_copy(holder.name, source)


# ---------------------------------------------------------------- G7
def line_hit(line):
    if URL_RE.search(line):
        return "url"
    if EMAIL_RE.search(line):
        return "email"
    if UNIX_ABS_RE.search(line) or DRIVE_RE.search(line):
        return "absolute path"
    for name, pattern in TOKEN_RES:
        if pattern.search(line):
            return name
    return None


def g7_hygiene():
    missing = missing_rels(PRODUCT_RELS)
    if missing:
        return FAIL, "missing " + ", ".join(missing)
    hits = []
    for rel in PRODUCT_RELS:
        path = REPO_ROOT / rel
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            return FAIL, rel + " unreadable: " + type(exc).__name__
        for number, line in enumerate(text.splitlines(), 1):
            kind = line_hit(line)
            if kind:
                hits.append(rel + ":" + str(number) + " " + kind)
                if len(hits) >= 8:
                    return FAIL, join_bits(hits, 8)
    if hits:
        return FAIL, join_bits(hits, 8)
    return PASS, "files=3"


# ---------------------------------------------------------------- G8
def g8_regression(before):
    parts = []
    blocked = False
    miss = False
    for rel in ("tools/check_007.py", "tools/check_008.py"):
        path = REPO_ROOT / rel
        if not path.is_file():
            miss = True
            parts.append(rel + " missing")
            continue
        proc = run_process([sys.executable, str(path)], REPO_ROOT, timeout=120)
        if could_not_start(proc):
            blocked = True
            parts.append(rel + " could not start rc=" + str(proc.returncode))
            continue
        line = result_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
        if proc.returncode != 0 or not line.startswith("RESULT: ALL PASS"):
            miss = True
        parts.append(rel + " exit " + str(proc.returncode) + " " + repr(line))
    changed = blob_changes(before, live_blobs())
    if changed:
        miss = True
        shown = ",".join(changed[:8])
        extra = "" if len(changed) <= 8 else " +" + str(len(changed) - 8)
        parts.append("live blobs changed: " + shown + extra)
    detail = "; ".join(parts)
    if miss:
        return FAIL, detail
    if blocked:
        return BLOCKED, detail
    return PASS, detail


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
        "G1 three workbench files exist; decide(snapshot, contract, policy, now) "
        "has no default, *args, or **kwargs; imports stay on the whitelist; "
        "banned calls are absent; import stop_policy is silent",
        g1_shape,
    )
    run_gate(
        "G2 scenarios.json matches the copied R4 base and R5 rows, title aside, "
        "and has no duplicate keys",
        g2_fixture,
    )
    run_gate(
        "G3 decide matches every R5 row, returns exactly the nine keys, "
        "keeps ui_message non-empty, leaves inputs unchanged, and is stable",
        g3_behavior,
    )
    run_gate(
        "G4 5184 probe-failure inputs never RELEASE or CLOSE and never enter "
        "a terminal state or RELEASING",
        g4_scan,
    )
    run_gate(
        "G5 unittest discover -s workbench/tests exits 0 and runs at least 10 tests",
        g5_tests,
    )
    run_gate(
        "G6 temp-copy mutants M1 M2 M3 each make the workbench tests fail",
        g6_mutants,
    )
    run_gate(
        "G7 the three workbench files contain no URL, email, absolute path, or token-like string",
        g7_hygiene,
    )
    run_gate(
        "G8 check_007.py and check_008.py exit 0 and live file hashes are unchanged",
        lambda: g8_regression(before),
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
