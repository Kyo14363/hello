"""Local mock workbench. Fake data only, bound to the loopback address.

Reads the fixture, serves the static page, and answers the JSON API.
Every transition goes through stop_policy.decide. Nothing is written back
to disk, and the audit log lives only in the process.
"""

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

import http.server

from stop_policy import decide


HOST = "127.0.0.1"

_ROOT = Path(__file__).resolve().parent
_UI = _ROOT / "ui"
_JOBS = _UI / "fixtures" / "jobs.json"

_RUNTIME = None

STATE_LABELS = {
    "REGISTERED": "已登記",
    "QUEUED": "排隊中",
    "STARTING": "準備中",
    "RUNNING": "執行中",
    "SAVING": "保存中",
    "COLLECTING": "收產出中",
    "RELEASING": "釋放中",
    "RELEASE_UNCONFIRMED": "釋放未確認",
    "PAUSED": "已暫停",
    "RECONCILING": "核對中",
    "UNKNOWN": "狀態不明",
    "BLOCKED": "需要你處理",
    "DONE": "完成",
    "FAILED": "失敗",
    "CANCELLED": "已取消",
}

BUSY_STATES = frozenset({
    "STARTING",
    "RUNNING",
    "SAVING",
    "COLLECTING",
    "RELEASING",
    "RELEASE_UNCONFIRMED",
    "RECONCILING",
    "UNKNOWN",
    "BLOCKED",
})

_TERMINAL = frozenset({"DONE", "FAILED", "CANCELLED"})

_HOST_LABELS = {
    "online": "在線",
    "shutting_down": "即將關機",
    "just_booted": "剛開機核對中",
}

_COMMANDS = frozenset({"stop_after_save", "stop_now", "pause", "resume"})
_BOT_ACTIONS = frozenset({"list_jobs", "get_status", "request_pause", "submit_job"})
_CRED_PARTS = (
    "token",
    "auth",
    "password",
    "secret",
    "cookie",
    "api_key",
    "apikey",
    "session",
)

_STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}

_CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}

_JSON_TYPE = "application/json; charset=utf-8"

_UI_TEXT = {
    "NOT_FOUND": "找不到這筆資料",
    "METHOD_NOT_ALLOWED": "不支援這個方法",
    "BAD_JSON": "請求內容不是 JSON 物件",
    "BAD_PARAM": "參數不正確",
    "CONFIRM_REQUIRED": "立即停止需要再確認一次",
    "INPUT_INVALID": "這筆假資料無法判斷",
    "CREDENTIAL_REFUSED": "不接受帶憑證的請求",
    "BAD_CALLER": "呼叫者必須是 Bot",
    "ACTION_NOT_ALLOWED": "這個動作不在原型範圍",
    "SERVER": "服務沒有完成這個請求",
}


def state_view(code):
    if isinstance(code, str) and code in STATE_LABELS:
        return {
            "code": code,
            "label": STATE_LABELS[code],
            "busy": code in BUSY_STATES,
            "terminal": code in _TERMINAL,
        }
    return {"code": code, "label": "狀態不明", "busy": True, "terminal": False}


def load_state():
    loaded = json.loads(_JOBS.read_text(encoding="utf-8"))
    return {
        "notice": loaded["notice"],
        "host": loaded["host"],
        "jobs": loaded["jobs"],
        "audits": [],
    }


def _error(code):
    return {"reason_code": code, "ui_message": _UI_TEXT[code]}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _route_of(path):
    if not isinstance(path, str):
        return ""
    split = urllib.parse.urlsplit(path)
    return urllib.parse.unquote(split.path)


def _parse_job(route):
    prefix = "/api/jobs/"
    if not route.startswith(prefix):
        return None
    rest = route[len(prefix):]
    if rest == "":
        return None
    if "/" not in rest:
        return rest, ""
    job_id, suffix = rest.split("/", 1)
    if job_id and suffix in ("command", "tick"):
        return job_id, suffix
    return None


def _find_job(state, job_id):
    for job in state["jobs"]:
        contract = job.get("contract")
        if isinstance(contract, dict) and contract.get("job_id") == job_id:
            return job
    return None


def _safe_decide(job):
    try:
        result = decide(job["snapshot"], job["contract"], job["policy"], job["now"])
    except ValueError:
        return None
    if not isinstance(result, dict):
        return None
    return result


def _release_label(snapshot):
    state = snapshot.get("state")
    if state == "RELEASE_UNCONFIRMED":
        return "釋放未確認"
    if state == "RELEASING":
        return "釋放中"
    if snapshot.get("release_check") == "confirmed_zero":
        return "已確認 0 active"
    return "無釋放回查"


def _minutes_to_cap(used, cap, rate):
    if not (_number(used) and _number(cap) and _number(rate)):
        return None
    if rate == 0 or used > cap:
        return None
    return (cap - used) / float(rate) * 60


def _blocker(job, decision):
    state = job["snapshot"].get("state") if isinstance(job.get("snapshot"), dict) else None
    notify = isinstance(decision, dict) and decision.get("notify_human") is True
    if state not in ("BLOCKED", "RELEASE_UNCONFIRMED", "UNKNOWN") and not notify:
        return None
    display = job.get("display") if isinstance(job.get("display"), dict) else {}
    note = display.get("note")
    if isinstance(note, str) and note != "":
        message = note
    elif isinstance(decision, dict):
        text = decision.get("ui_message")
        if isinstance(text, str) and text != "":
            message = text
        else:
            message = "狀態不明，請先核對"
    else:
        message = "狀態不明，請先核對"
    return {
        "message": message,
        "suggested": ["tick", "stop_after_save", "stop_now"],
    }


def _submitter_label(submitted):
    if submitted == "human":
        return "人"
    if isinstance(submitted, str) and submitted.startswith("bot:"):
        return "Bot"
    return None


def job_summary(notice, job):
    snap = job["snapshot"] if isinstance(job.get("snapshot"), dict) else {}
    contract = job["contract"] if isinstance(job.get("contract"), dict) else {}
    display = job["display"] if isinstance(job.get("display"), dict) else {}
    view = state_view(snap.get("state"))
    decided = _safe_decide(job)
    if decided is None:
        decision = None
        decision_error = "INPUT_INVALID"
        busy = True
    else:
        decision = decided
        decision_error = None
        busy = view["busy"]
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}
    used = snap.get("cu_used")
    cap = contract.get("cu_cap")
    rate = display.get("cu_rate_per_hour")
    ratio = contract.get("cu_soft_ratio")
    if _number(ratio) and _number(cap):
        soft = ratio * cap
    else:
        soft = None
    return {
        "job_id": contract.get("job_id"),
        "title": display.get("title"),
        "job_type": contract.get("job_type"),
        "state": snap.get("state"),
        "state_label": view["label"],
        "busy": busy,
        "terminal": view["terminal"],
        "submitted_by": contract.get("submitted_by"),
        "submitter_label": _submitter_label(contract.get("submitted_by")),
        "human_hold": snap.get("human_hold"),
        "progress": {
            "value": progress.get("value"),
            "total": display.get("progress_total"),
        },
        "cu": {
            "used": used,
            "soft": soft,
            "cap": cap,
            "balance": display.get("cu_balance"),
            "rate_per_hour": rate,
            "minutes_to_cap": _minutes_to_cap(used, cap, rate),
            "notice": notice,
        },
        "release_label": _release_label(snap),
        "decision": decision,
        "decision_error": decision_error,
        "blocker": _blocker(job, decided),
    }


def _contract_summary(contract):
    if not isinstance(contract, dict):
        return {}
    heartbeat = contract.get("heartbeat")
    if not isinstance(heartbeat, dict):
        heartbeat = {}
    return {
        "job_id": contract.get("job_id"),
        "template_id": contract.get("template_id"),
        "job_type": contract.get("job_type"),
        "workload_kind": contract.get("workload_kind"),
        "cu_cap": contract.get("cu_cap"),
        "cu_soft_ratio": contract.get("cu_soft_ratio"),
        "max_minutes": contract.get("max_minutes"),
        "stall_minutes": heartbeat.get("stall_minutes"),
        "on_host_offline": contract.get("on_host_offline"),
        "submitted_by": contract.get("submitted_by"),
    }


def _job_detail(state, job):
    summary = job_summary(state["notice"], job)
    snap = job["snapshot"] if isinstance(job.get("snapshot"), dict) else {}
    display = job["display"] if isinstance(job.get("display"), dict) else {}
    files = display.get("files")
    timeline = display.get("timeline")
    summary["checkpoint"] = snap.get("checkpoint")
    summary["files"] = files if isinstance(files, list) else []
    summary["timeline"] = timeline if isinstance(timeline, list) else []
    summary["contract_summary"] = _contract_summary(job.get("contract"))
    summary["audit"] = _audits_for(state, summary.get("job_id"))
    return summary


def _audits_for(state, job_id):
    found = []
    for record in state["audits"]:
        if record.get("job_id") == job_id:
            found.append(record)
    return found


def _overview(state):
    host = state.get("host")
    return {
        "notice": state.get("notice"),
        "host": host,
        "host_label": _HOST_LABELS.get(host),
        "wind_down": _wind_down(state),
        "jobs": [job_summary(state.get("notice"), job) for job in state["jobs"]],
    }


def _wind_down(state):
    if state.get("host") == "online":
        return []
    found = []
    for job in state["jobs"]:
        decision = _safe_decide(job)
        if not isinstance(decision, dict):
            continue
        shutdown = (
            decision.get("action") == "REQUEST_SAVE"
            and decision.get("reason_code") == "HOST_SHUTDOWN"
        )
        offline = decision.get("reason_code") == "HOST_OFFLINE_REMOTE_RUNNING"
        if shutdown or offline:
            contract = job.get("contract") if isinstance(job.get("contract"), dict) else {}
            found.append(contract.get("job_id"))
    return found


def _moment(job):
    if not isinstance(job, dict):
        return None
    now = job.get("now")
    if _number(now):
        return now
    return None


def _meta(at, caller, action, job_id, result):
    return {
        "at": at,
        "caller": caller,
        "action": action,
        "job_id": job_id,
        "result": result,
    }


def _add_audit(state, meta):
    state["audits"].append({
        "at": meta["at"],
        "caller": meta["caller"],
        "action": meta["action"],
        "job_id": meta["job_id"],
        "result": meta["result"],
    })


def _clear_requests(snapshot):
    snapshot["human_command"] = "none"
    snapshot["bot_request"] = "none"


def _apply_move(job, mode, command):
    snapshot = job["snapshot"]
    if mode == "command":
        snapshot["human_command"] = command
    elif mode == "pause":
        snapshot["bot_request"] = "pause"
    try:
        result = decide(snapshot, job["contract"], job["policy"], job["now"])
    except ValueError:
        _clear_requests(snapshot)
        return None
    if not isinstance(result, dict):
        _clear_requests(snapshot)
        return None
    if result.get("action") != "REJECT_REQUEST":
        snapshot["state"] = result.get("next_state")
        snapshot["human_hold"] = result.get("human_hold_after")
        snapshot["stop_intent"] = result.get("stop_intent")
    _clear_requests(snapshot)
    return result


def _apply_body(state, job, result):
    return {
        "job_id": job["contract"]["job_id"],
        "accepted": result.get("action") != "REJECT_REQUEST",
        "decision": result,
        "job": job_summary(state["notice"], job),
    }


def _progress_of(job):
    snap = job["snapshot"] if isinstance(job.get("snapshot"), dict) else {}
    display = job["display"] if isinstance(job.get("display"), dict) else {}
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}
    return {"value": progress.get("value"), "total": display.get("progress_total")}


def _list_row(job):
    snap = job["snapshot"] if isinstance(job.get("snapshot"), dict) else {}
    contract = job["contract"] if isinstance(job.get("contract"), dict) else {}
    decided = _safe_decide(job)
    view = state_view(snap.get("state"))
    if decided is None:
        reason = "INPUT_INVALID"
    else:
        reason = decided.get("reason_code")
    return {
        "job_id": contract.get("job_id"),
        "state": snap.get("state"),
        "state_label": view["label"],
        "progress": _progress_of(job),
        "reason_code": reason,
    }


def _status_body(job):
    snap = job["snapshot"] if isinstance(job.get("snapshot"), dict) else {}
    contract = job["contract"] if isinstance(job.get("contract"), dict) else {}
    decided = _safe_decide(job)
    view = state_view(snap.get("state"))
    if decided is None:
        reason = "INPUT_INVALID"
        message = _UI_TEXT["INPUT_INVALID"]
    else:
        reason = decided.get("reason_code")
        message = decided.get("ui_message")
    return {
        "ok": True,
        "job_id": contract.get("job_id"),
        "state": snap.get("state"),
        "state_label": view["label"],
        "progress": _progress_of(job),
        "reason_code": reason,
        "ui_message": message,
    }


def _cred_name(name):
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    for part in _CRED_PARTS:
        if part in lowered:
            return True
    return False


def _collect_strings(value, found):
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, found)


def _banned_strings(body):
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if _cred_name(key):
                    _collect_strings(value, found)
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(body)
    return found


def _has_credential(body):
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if _cred_name(key) or walk(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if walk(item):
                    return True
        return False

    return walk(body)


def _bot_caller(body, banned):
    caller = body.get("caller") if isinstance(body, dict) else None
    if isinstance(caller, str) and caller.startswith("bot:") and caller not in banned:
        return caller
    return "human"


def _bot_action_name(body, banned):
    action = body.get("action") if isinstance(body, dict) else None
    if isinstance(action, str) and action not in banned and len(action) <= 64:
        return action
    return "bot"


def _known_state(code):
    return isinstance(code, str) and code in STATE_LABELS


def _post_command(state, job, body):
    command = body.get("command")
    moment = _moment(job)
    job_id = job["contract"]["job_id"]
    if command not in _COMMANDS:
        return 400, _error("BAD_PARAM"), _meta(moment, "human", "command", job_id, "BAD_PARAM")
    if command == "stop_now" and body.get("confirm") is not True:
        return (
            409,
            _error("CONFIRM_REQUIRED"),
            _meta(moment, "human", "stop_now", job_id, "CONFIRM_REQUIRED"),
        )
    result = _apply_move(job, "command", command)
    if result is None:
        return (
            422,
            _error("INPUT_INVALID"),
            _meta(moment, "human", command, job_id, "INPUT_INVALID"),
        )
    return (
        200,
        _apply_body(state, job, result),
        _meta(moment, "human", command, job_id, result.get("reason_code")),
    )


def _post_tick(state, job):
    moment = _moment(job)
    job_id = job["contract"]["job_id"]
    result = _apply_move(job, "tick", None)
    if result is None:
        return (
            422,
            _error("INPUT_INVALID"),
            _meta(moment, "human", "tick", job_id, "INPUT_INVALID"),
        )
    return (
        200,
        _apply_body(state, job, result),
        _meta(moment, "human", "tick", job_id, result.get("reason_code")),
    )


def _post_host(state, body):
    host = body.get("host")
    if host not in _HOST_LABELS:
        return 400, _error("BAD_PARAM"), _meta(None, "human", "host", None, "BAD_PARAM")
    state["host"] = host
    for job in state["jobs"]:
        snapshot = job.get("snapshot")
        if isinstance(snapshot, dict):
            snapshot["host"] = host
    payload = {
        "host": host,
        "host_label": _HOST_LABELS[host],
        "wind_down": _wind_down(state),
    }
    return 200, payload, _meta(None, "human", "host", None, "OK")


def _post_reset(state):
    fresh = load_state()
    state.clear()
    state.update(fresh)
    payload = {"notice": state["notice"], "host": state["host"]}
    return 200, payload, _meta(None, "human", "reset", None, "RESET")


def _post_bot(state, body):
    banned = _banned_strings(body)
    caller = _bot_caller(body, banned)
    action_name = _bot_action_name(body, banned)
    if _has_credential(body):
        return (
            400,
            _error("CREDENTIAL_REFUSED"),
            _meta(None, caller, action_name, None, "CREDENTIAL_REFUSED"),
        )
    raw_caller = body.get("caller")
    if not isinstance(raw_caller, str) or not raw_caller.startswith("bot:"):
        return 400, _error("BAD_CALLER"), _meta(None, "human", action_name, None, "BAD_CALLER")
    action = body.get("action")
    if action not in _BOT_ACTIONS:
        return (
            403,
            _error("ACTION_NOT_ALLOWED"),
            _meta(None, caller, action_name, None, "ACTION_NOT_ALLOWED"),
        )
    if action == "list_jobs":
        return _bot_list(state, body, caller)
    if action == "get_status":
        return _bot_status(state, body, caller)
    if action == "request_pause":
        return _bot_pause(state, body, caller)
    return (
        200,
        {"ok": True, "accepted": False, "reason_code": "NOT_IN_PROTOTYPE"},
        _meta(None, caller, "submit_job", None, "NOT_IN_PROTOTYPE"),
    )


def _bot_list(state, body, caller):
    if "state" in body and not _known_state(body.get("state")):
        return 400, _error("BAD_PARAM"), _meta(None, caller, "list_jobs", None, "BAD_PARAM")
    wanted = body.get("state") if "state" in body else None
    rows = []
    for job in state["jobs"]:
        snap = job.get("snapshot") if isinstance(job.get("snapshot"), dict) else {}
        if wanted is not None and snap.get("state") != wanted:
            continue
        rows.append(_list_row(job))
    return 200, {"ok": True, "jobs": rows}, _meta(None, caller, "list_jobs", None, "OK")


def _bot_status(state, body, caller):
    job_id = body.get("job_id")
    if not isinstance(job_id, str):
        return 400, _error("BAD_PARAM"), _meta(None, caller, "get_status", None, "BAD_PARAM")
    job = _find_job(state, job_id)
    if job is None:
        return 404, _error("NOT_FOUND"), _meta(None, caller, "get_status", None, "NOT_FOUND")
    payload = _status_body(job)
    reason = payload.get("reason_code")
    return 200, payload, _meta(_moment(job), caller, "get_status", job_id, reason)


def _bot_pause(state, body, caller):
    job_id = body.get("job_id")
    if not isinstance(job_id, str):
        return (
            400,
            _error("BAD_PARAM"),
            _meta(None, caller, "request_pause", None, "BAD_PARAM"),
        )
    job = _find_job(state, job_id)
    if job is None:
        return (
            404,
            _error("NOT_FOUND"),
            _meta(None, caller, "request_pause", None, "NOT_FOUND"),
        )
    result = _apply_move(job, "pause", None)
    moment = _moment(job)
    if result is None:
        return (
            422,
            _error("INPUT_INVALID"),
            _meta(moment, caller, "request_pause", job_id, "INPUT_INVALID"),
        )
    payload = {
        "ok": True,
        "job_id": job["contract"]["job_id"],
        "accepted": result.get("action") != "REJECT_REQUEST",
        "reason_code": result.get("reason_code"),
    }
    return (
        200,
        payload,
        _meta(moment, caller, "request_pause", job_id, result.get("reason_code")),
    )


def _missing_job(job_id):
    return 404, _error("NOT_FOUND"), _meta(None, "human", "post", job_id, "NOT_FOUND")


def _dispatch_post(state, route, body):
    if route == "/api/reset":
        return _post_reset(state)
    if route == "/api/host":
        return _post_host(state, body)
    if route == "/api/bot":
        return _post_bot(state, body)
    parsed = _parse_job(route)
    if parsed is None:
        return 404, _error("NOT_FOUND"), _meta(None, "human", "post", None, "NOT_FOUND")
    job_id, suffix = parsed
    job = _find_job(state, job_id)
    if job is None:
        return _missing_job(job_id)
    if suffix == "command":
        return _post_command(state, job, body)
    if suffix == "tick":
        return _post_tick(state, job)
    return 404, _error("NOT_FOUND"), _meta(None, "human", "post", None, "NOT_FOUND")


def _dispatch_get(state, route):
    if route in _STATIC:
        return 200, {"static": _STATIC[route]}
    if route == "/api/jobs":
        return 200, _overview(state)
    parsed = _parse_job(route)
    if parsed is None or parsed[1] != "":
        return 404, _error("NOT_FOUND")
    job = _find_job(state, parsed[0])
    if job is None:
        return 404, _error("NOT_FOUND")
    return 200, _job_detail(state, job)


def handle(state, method, path, body):
    route = _route_of(path)
    if method not in ("GET", "POST"):
        return 405, _error("METHOD_NOT_ALLOWED")
    if method == "GET":
        return _dispatch_get(state, route)
    if not isinstance(body, dict):
        _add_audit(state, _meta(None, "human", "post", None, "BAD_JSON"))
        return 400, _error("BAD_JSON")
    status, payload, meta = _dispatch_post(state, route, body)
    _add_audit(state, meta)
    return status, payload


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _static_bytes(name):
    if name not in _CONTENT_TYPES:
        return None
    return (_UI / name).read_bytes()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._respond("GET")

    def do_POST(self):
        self._respond("POST")

    def do_PUT(self):
        self._respond("PUT")

    def do_DELETE(self):
        self._respond("DELETE")

    def do_PATCH(self):
        self._respond("PATCH")

    def do_OPTIONS(self):
        self._respond("OPTIONS")

    def do_HEAD(self):
        self._respond("HEAD")

    def log_message(self, fmt, *args):
        return

    def _read_body(self):
        header = self.headers.get("Content-Length")
        if header is None or header == "":
            return None
        try:
            length = int(header)
        except ValueError:
            return None
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            return None

    def _build(self, method):
        body = self._read_body() if method == "POST" else None
        if _RUNTIME is None:
            return 500, _json_bytes(_error("SERVER")), _JSON_TYPE
        status, payload = handle(_RUNTIME, method, self.path, body)
        if (
            status == 200
            and isinstance(payload, dict)
            and set(payload) == {"static"}
            and payload.get("static") in _CONTENT_TYPES
        ):
            name = payload["static"]
            data = _static_bytes(name)
            if data is None:
                return 404, _json_bytes(_error("NOT_FOUND")), _JSON_TYPE
            return 200, data, _CONTENT_TYPES[name]
        return status, _json_bytes(payload), _JSON_TYPE

    def _respond(self, method):
        try:
            status, data, content_type = self._build(method)
        except Exception:
            status = 500
            data = _json_bytes(_error("SERVER"))
            content_type = _JSON_TYPE
        self._write(status, data, content_type)

    def _write(self, status, data, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main():
    global _RUNTIME
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    _RUNTIME = load_state()
    server = http.server.HTTPServer((HOST, args.port), Handler)
    try:
        bound = server.server_address[1]
        print("LISTENING " + HOST + " " + str(bound), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
