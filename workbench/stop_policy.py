"""Pure stop decision for one local workbench job.

`decide` reads the validated fields and returns the next action. It does not
touch the clock, the disk, the network, or its inputs. Times are minutes on
the caller's fake timeline.
"""


_STATES = frozenset({
    "REGISTERED",
    "QUEUED",
    "STARTING",
    "RUNNING",
    "SAVING",
    "COLLECTING",
    "RELEASING",
    "RELEASE_UNCONFIRMED",
    "PAUSED",
    "RECONCILING",
    "UNKNOWN",
    "BLOCKED",
    "DONE",
    "FAILED",
    "CANCELLED",
})

_TERMINAL = frozenset({"DONE", "FAILED", "CANCELLED"})

_PROBED = frozenset({
    "STARTING",
    "RUNNING",
    "SAVING",
    "COLLECTING",
    "RELEASING",
    "RELEASE_UNCONFIRMED",
    "BLOCKED",
})

_PROBE_STATUS = frozenset({"ok", "failed", "timeout"})
_HUMAN_COMMANDS = frozenset({
    "none", "stop_after_save", "stop_now", "pause", "resume",
})
_BOT_REQUESTS = frozenset({"none", "pause", "resume"})
_STOP_INTENTS = frozenset({"none", "pause", "finish", "fail"})
_HOSTS = frozenset({"online", "shutting_down", "just_booted"})
_REMOTES = frozenset({"running", "finished", "released", "unreachable"})
_RELEASE_CHECKS = frozenset({
    "not_started", "confirmed_zero", "active_nonzero", "check_failed",
})
_WORKLOADS = frozenset({"training", "batch_inference"})
_OFFLINE = frozenset({"pause_safely", "continue_until_checkpoint"})
_MODES = frozenset({"A", "B", "C"})

_MESSAGES = {
    "TERMINAL": "此工作已在終態，維持現況。",
    "HUMAN_STOP": "已接受人工停止，依指令收尾。",
    "HUMAN_PAUSE": "已接受人工暫停，先保存再停下。",
    "HUMAN_RESUME": "已接受人工續跑，工作回到佇列。",
    "BAD_STATE": "目前狀態不能執行這個指令。",
    "HUMAN_HOLD": "工作有人工鎖，拒絕這次請求。",
    "BOT_PAUSE": "已接受 Bot 暫停請求，先保存再停下。",
    "NOT_OWNER": "Bot 只能續跑自己提交的工作。",
    "BOT_RESUME": "已接受 Bot 續跑請求，工作回到佇列。",
    "BOOT_RECONCILE": "本機剛開機，先核對進度與遠端狀態。",
    "PROBE_UNCERTAIN": "查詢結果不確定，先不要當成閒置或完成。",
    "RECONCILED_RUNNING": "核對完成，遠端仍在執行。",
    "RECONCILED_COLLECT": "核對完成，開始收取尚未下載的產出。",
    "RECONCILED_RELEASE": "核對完成，產出已齊，準備釋放資源。",
    "RECONCILED_PAUSED": "核對完成，工作改為暫停並可從既有進度續跑。",
    "RECONCILE_CONFLICT": "核對結果互相矛盾，需要人處理。",
    "HOST_SHUTDOWN": "本機即將關機，依關機規則處理這項工作。",
    "HOST_OFFLINE_REMOTE_RUNNING": "本機即將關機，遠端工作會繼續跑到下一個檢查點。",
    "PROBE_RETRY": "查詢失敗，稍後再查一次。",
    "CU_HARD_CAP_UNKNOWN": "狀態不明且已碰到運算單位硬上限，請人決定。",
    "UNKNOWN_TOO_LONG": "狀態不明太久，請人處理。",
    "PROBE_RECOVERED": "查詢已恢復，開始核對。",
    "RELEASE_CONFIRMED": "釋放已確認，沒有仍在使用的資源。",
    "RELEASE_PENDING": "釋放回查尚未開始，先等待。",
    "RELEASE_NOT_CONFIRMED": "釋放尚未確認，不能顯示為完成。",
    "SHA_MISMATCH": "產出的雜湊不符，依剩餘次數重試或轉人處理。",
    "COLLECT_PENDING": "還有產出尚未下載驗證。",
    "OUTPUTS_VERIFIED": "產出已驗證，準備釋放資源。",
    "SAVE_CONFIRMED": "檢查點已確認，開始收取產出。",
    "SAVE_PENDING": "保存尚未確認，繼續等待。",
    "CU_HARD_CAP": "已達運算單位硬上限，開始收取已保存的產出。",
    "MAX_TIME": "已達最長執行時間，開始收取已保存的產出。",
    "CU_HARD_CAP_UNSAVED": "已達運算單位硬上限，還有未保存的產出。",
    "MAX_TIME_UNSAVED": "已達最長執行時間，還有未保存的產出。",
    "CU_GRACE_EXHAUSTED": "保存寬限已用完，未保存的產出可能遺失。",
    "CU_SOFT_CAP": "已達運算單位軟上限，先保存再暫停。",
    "MAX_TIME_SOON": "最長執行時間將到，先保存再暫停。",
    "STALLED": "進度已停滯，收取已保存的產出後結束。",
    "COMPLETE": "工作已完成，開始收取產出。",
    "COMPLETE_SAVING": "工作已完成，先保存再收取產出。",
    "OK": "目前狀態正常，繼續執行。",
}


def _need(container, key, label):
    if not isinstance(container, dict) or key not in container:
        raise ValueError("missing " + label)
    return container[key]


def _choice(value, allowed, label):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("bad " + label)
    return value


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("bad " + label)
    return value


def _integer_or_null(value, label):
    if value is None:
        return None
    return _integer(value, label)


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("bad " + label)
    return value


def _number_or_null(value, label):
    if value is None:
        return None
    return _number(value, label)


def _boolean(value, label):
    if not isinstance(value, bool):
        raise ValueError("bad " + label)
    return value


def _submitted_by(value):
    if value == "human":
        return value
    if isinstance(value, str) and value.startswith("bot:") and len(value) > 4:
        return value
    raise ValueError("bad contract.submitted_by")


def _validate(snapshot, contract, policy, now):
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        raise ValueError("bad now")

    probe = _need(snapshot, "probe", "snapshot.probe")
    progress = _need(snapshot, "progress", "snapshot.progress")
    checkpoint = _need(snapshot, "checkpoint", "snapshot.checkpoint")
    outputs = _need(snapshot, "outputs", "snapshot.outputs")
    heartbeat = _need(contract, "heartbeat", "contract.heartbeat")

    state = _choice(_need(snapshot, "state", "snapshot.state"), _STATES, "snapshot.state")
    probe_status = _choice(
        _need(probe, "status", "snapshot.probe.status"),
        _PROBE_STATUS,
        "snapshot.probe.status",
    )
    consecutive_failures = _integer(
        _need(probe, "consecutive_failures", "snapshot.probe.consecutive_failures"),
        "snapshot.probe.consecutive_failures",
    )
    last_advanced_at = _number(
        _need(progress, "last_advanced_at", "snapshot.progress.last_advanced_at"),
        "snapshot.progress.last_advanced_at",
    )
    step = _integer_or_null(
        _need(checkpoint, "step", "snapshot.checkpoint.step"),
        "snapshot.checkpoint.step",
    )
    confirmed = _boolean(
        _need(checkpoint, "confirmed", "snapshot.checkpoint.confirmed"),
        "snapshot.checkpoint.confirmed",
    )
    unsaved = _integer(
        _need(outputs, "unsaved", "snapshot.outputs.unsaved"),
        "snapshot.outputs.unsaved",
    )
    pending_download = _integer(
        _need(outputs, "pending_download", "snapshot.outputs.pending_download"),
        "snapshot.outputs.pending_download",
    )
    first_unverified = _integer_or_null(
        _need(outputs, "first_unverified", "snapshot.outputs.first_unverified"),
        "snapshot.outputs.first_unverified",
    )
    sha_mismatch = _integer(
        _need(outputs, "sha_mismatch", "snapshot.outputs.sha_mismatch"),
        "snapshot.outputs.sha_mismatch",
    )
    download_retries_used = _integer(
        _need(outputs, "download_retries_used", "snapshot.outputs.download_retries_used"),
        "snapshot.outputs.download_retries_used",
    )
    cu_used = _number(_need(snapshot, "cu_used", "snapshot.cu_used"), "snapshot.cu_used")
    elapsed_minutes = _number(
        _need(snapshot, "elapsed_minutes", "snapshot.elapsed_minutes"),
        "snapshot.elapsed_minutes",
    )
    limit_hit_at = _number_or_null(
        _need(snapshot, "limit_hit_at", "snapshot.limit_hit_at"),
        "snapshot.limit_hit_at",
    )
    unknown_since = _number_or_null(
        _need(snapshot, "unknown_since", "snapshot.unknown_since"),
        "snapshot.unknown_since",
    )
    human_command = _choice(
        _need(snapshot, "human_command", "snapshot.human_command"),
        _HUMAN_COMMANDS,
        "snapshot.human_command",
    )
    bot_request = _choice(
        _need(snapshot, "bot_request", "snapshot.bot_request"),
        _BOT_REQUESTS,
        "snapshot.bot_request",
    )
    human_hold = _boolean(
        _need(snapshot, "human_hold", "snapshot.human_hold"),
        "snapshot.human_hold",
    )
    stop_intent = _choice(
        _need(snapshot, "stop_intent", "snapshot.stop_intent"),
        _STOP_INTENTS,
        "snapshot.stop_intent",
    )
    host = _choice(_need(snapshot, "host", "snapshot.host"), _HOSTS, "snapshot.host")
    remote = _choice(
        _need(snapshot, "remote", "snapshot.remote"),
        _REMOTES,
        "snapshot.remote",
    )
    release_check = _choice(
        _need(snapshot, "release_check", "snapshot.release_check"),
        _RELEASE_CHECKS,
        "snapshot.release_check",
    )
    release_retries_used = _integer(
        _need(snapshot, "release_retries_used", "snapshot.release_retries_used"),
        "snapshot.release_retries_used",
    )
    done_signal = _boolean(
        _need(snapshot, "done_signal", "snapshot.done_signal"),
        "snapshot.done_signal",
    )
    workload_kind = _choice(
        _need(contract, "workload_kind", "contract.workload_kind"),
        _WORKLOADS,
        "contract.workload_kind",
    )
    cu_cap = _number(_need(contract, "cu_cap", "contract.cu_cap"), "contract.cu_cap")
    cu_soft_ratio = _number(
        _need(contract, "cu_soft_ratio", "contract.cu_soft_ratio"),
        "contract.cu_soft_ratio",
    )
    max_minutes = _number(
        _need(contract, "max_minutes", "contract.max_minutes"),
        "contract.max_minutes",
    )
    stall_minutes = _number(
        _need(heartbeat, "stall_minutes", "contract.heartbeat.stall_minutes"),
        "contract.heartbeat.stall_minutes",
    )
    on_host_offline = _choice(
        _need(contract, "on_host_offline", "contract.on_host_offline"),
        _OFFLINE,
        "contract.on_host_offline",
    )
    submitted_by = _submitted_by(_need(contract, "submitted_by", "contract.submitted_by"))
    probe_confirm_count = _integer(
        _need(policy, "probe_confirm_count", "policy.probe_confirm_count"),
        "policy.probe_confirm_count",
    )
    unknown_alert_minutes = _number(
        _need(policy, "unknown_alert_minutes", "policy.unknown_alert_minutes"),
        "policy.unknown_alert_minutes",
    )
    mode = _choice(
        _need(policy, "budget_conflict_mode", "policy.budget_conflict_mode"),
        _MODES,
        "policy.budget_conflict_mode",
    )
    grace_cu_ratio = _number(
        _need(policy, "grace_cu_ratio", "policy.grace_cu_ratio"),
        "policy.grace_cu_ratio",
    )
    grace_minutes = _number(
        _need(policy, "grace_minutes", "policy.grace_minutes"),
        "policy.grace_minutes",
    )
    save_before_max_minutes = _number(
        _need(policy, "save_before_max_minutes", "policy.save_before_max_minutes"),
        "policy.save_before_max_minutes",
    )
    download_retry_limit = _integer(
        _need(policy, "download_retry_limit", "policy.download_retry_limit"),
        "policy.download_retry_limit",
    )
    release_recheck_limit = _integer(
        _need(policy, "release_recheck_limit", "policy.release_recheck_limit"),
        "policy.release_recheck_limit",
    )

    saved = confirmed is True and unsaved == 0
    hard = cu_used >= cu_cap
    timeup = elapsed_minutes >= max_minutes
    if limit_hit_at is None:
        over = 0
    else:
        over = now - limit_hit_at
    grace_out = (
        cu_used >= (cu_cap + (cu_cap * grace_cu_ratio)) or over >= grace_minutes
    )

    return {
        "now": now,
        "state": state,
        "probe_status": probe_status,
        "consecutive_failures": consecutive_failures,
        "last_advanced_at": last_advanced_at,
        "step": step,
        "confirmed": confirmed,
        "unsaved": unsaved,
        "pending_download": pending_download,
        "first_unverified": first_unverified,
        "sha_mismatch": sha_mismatch,
        "download_retries_used": download_retries_used,
        "cu_used": cu_used,
        "elapsed_minutes": elapsed_minutes,
        "limit_hit_at": limit_hit_at,
        "unknown_since": unknown_since,
        "human_command": human_command,
        "bot_request": bot_request,
        "human_hold": human_hold,
        "stop_intent": stop_intent,
        "host": host,
        "remote": remote,
        "release_check": release_check,
        "release_retries_used": release_retries_used,
        "done_signal": done_signal,
        "workload_kind": workload_kind,
        "cu_cap": cu_cap,
        "cu_soft_ratio": cu_soft_ratio,
        "max_minutes": max_minutes,
        "stall_minutes": stall_minutes,
        "on_host_offline": on_host_offline,
        "submitted_by": submitted_by,
        "probe_confirm_count": probe_confirm_count,
        "unknown_alert_minutes": unknown_alert_minutes,
        "mode": mode,
        "grace_cu_ratio": grace_cu_ratio,
        "grace_minutes": grace_minutes,
        "save_before_max_minutes": save_before_max_minutes,
        "download_retry_limit": download_retry_limit,
        "release_recheck_limit": release_recheck_limit,
        "saved": saved,
        "hard": hard,
        "limit": hard or timeup,
        "grace_out": grace_out,
    }


def _out(action, next_state, reason, hold, intent, risk=False, notify=False, unit=None):
    return {
        "action": action,
        "next_state": next_state,
        "reason_code": reason,
        "ui_message": _MESSAGES[reason],
        "data_at_risk": True if risk else False,
        "notify_human": True if notify else False,
        "human_hold_after": True if hold else False,
        "stop_intent": intent,
        "from_unit": unit,
    }


def _limit(v, hold):
    """Shared hard-cap and max-time handling. Always pauses afterwards."""
    intent = "pause"
    if v["saved"]:
        reason = "CU_HARD_CAP" if v["hard"] else "MAX_TIME"
        return _out("COLLECT", "COLLECTING", reason, hold, intent)
    reason = "CU_HARD_CAP_UNSAVED" if v["hard"] else "MAX_TIME_UNSAVED"
    mode = v["mode"]
    if mode == "A":
        return _out("RELEASE", "RELEASING", reason, hold, intent, risk=True, notify=True)
    if mode == "B":
        return _out("REQUEST_SAVE", "SAVING", reason, hold, intent)
    if v["grace_out"]:
        return _out(
            "RELEASE", "RELEASING", "CU_GRACE_EXHAUSTED", hold, intent,
            risk=True, notify=True,
        )
    return _out("REQUEST_SAVE", "SAVING", reason, hold, intent)


def _human(v, hold, intent):
    command = v["human_command"]
    state = v["state"]
    if command == "stop_now":
        risk = (not v["saved"]) or v["pending_download"] > 0
        return _out("RELEASE", "RELEASING", "HUMAN_STOP", True, "pause", risk=risk)
    if command == "stop_after_save":
        return _out("REQUEST_SAVE", "SAVING", "HUMAN_STOP", True, "pause")
    if command == "pause":
        return _out("REQUEST_SAVE", "SAVING", "HUMAN_PAUSE", True, "pause")
    if state == "PAUSED":
        return _out("CONTINUE", "QUEUED", "HUMAN_RESUME", False, "none")
    return _out("REJECT_REQUEST", state, "BAD_STATE", hold, intent)


def _bot(v, hold, intent):
    state = v["state"]
    if hold is True:
        return _out("REJECT_REQUEST", state, "HUMAN_HOLD", hold, intent)
    if v["bot_request"] == "pause":
        if state == "RUNNING":
            return _out("REQUEST_SAVE", "SAVING", "BOT_PAUSE", hold, "pause")
        return _out("REJECT_REQUEST", state, "BAD_STATE", hold, intent)
    if state != "PAUSED":
        return _out("REJECT_REQUEST", state, "BAD_STATE", hold, intent)
    if not v["submitted_by"].startswith("bot:"):
        return _out("REJECT_REQUEST", state, "NOT_OWNER", hold, intent)
    return _out("CONTINUE", "QUEUED", "BOT_RESUME", hold, "none")


def _reconcile(v, hold, intent):
    remote = v["remote"]
    if v["probe_status"] != "ok" or remote == "unreachable":
        return _out(
            "MARK_UNKNOWN", "UNKNOWN", "PROBE_UNCERTAIN", hold, intent, notify=True,
        )
    if remote == "running":
        return _out("CONTINUE", "RUNNING", "RECONCILED_RUNNING", hold, intent)
    if remote == "finished" and v["pending_download"] > 0:
        return _out(
            "COLLECT", "COLLECTING", "RECONCILED_COLLECT", hold, intent,
            unit=v["first_unverified"],
        )
    if remote == "finished":
        return _out("RELEASE", "RELEASING", "RECONCILED_RELEASE", hold, intent)
    if v["workload_kind"] == "training":
        if v["confirmed"] is True:
            return _out(
                "CLOSE", "PAUSED", "RECONCILED_PAUSED", hold, intent, unit=v["step"],
            )
        return _out(
            "ESCALATE", "BLOCKED", "RECONCILE_CONFLICT", hold, intent, notify=True,
        )
    lost = v["pending_download"] > 0
    return _out(
        "CLOSE", "PAUSED", "RECONCILED_PAUSED", hold, intent,
        risk=lost, notify=lost, unit=v["first_unverified"],
    )


def _shutdown(v, hold, intent):
    state = v["state"]
    if state in ("REGISTERED", "QUEUED"):
        return _out("WAIT", state, "HOST_SHUTDOWN", hold, intent)
    if state in ("STARTING", "RUNNING"):
        if v["on_host_offline"] == "pause_safely":
            return _out("REQUEST_SAVE", "SAVING", "HOST_SHUTDOWN", hold, "pause")
        return _out(
            "CONTINUE", state, "HOST_OFFLINE_REMOTE_RUNNING", hold, intent, notify=True,
        )
    return None


def _probe_uncertain(v, hold, intent):
    if v["consecutive_failures"] < v["probe_confirm_count"]:
        return _out("WAIT", v["state"], "PROBE_RETRY", hold, intent)
    return _out("MARK_UNKNOWN", "UNKNOWN", "PROBE_UNCERTAIN", hold, intent)


def _unknown(v, hold, intent):
    if v["hard"] and v["grace_out"]:
        return _out(
            "ESCALATE", "BLOCKED", "CU_HARD_CAP_UNKNOWN", hold, intent, notify=True,
        )
    since = v["unknown_since"]
    if since is not None and (v["now"] - since) >= v["unknown_alert_minutes"]:
        return _out(
            "ESCALATE", "BLOCKED", "UNKNOWN_TOO_LONG", hold, intent, notify=True,
        )
    if v["probe_status"] == "ok":
        return _out("RECONCILE", "RECONCILING", "PROBE_RECOVERED", hold, intent)
    return _out("WAIT", "UNKNOWN", "PROBE_UNCERTAIN", hold, intent)


def _release_check(v, hold, intent):
    check = v["release_check"]
    state = v["state"]
    if check == "confirmed_zero":
        if intent == "finish":
            nxt = "DONE"
        elif intent == "fail":
            nxt = "FAILED"
        else:
            nxt = "PAUSED"
        return _out("CLOSE", nxt, "RELEASE_CONFIRMED", hold, "none")
    if check == "not_started":
        return _out("WAIT", state, "RELEASE_PENDING", hold, intent)
    if v["release_retries_used"] < v["release_recheck_limit"]:
        return _out(
            "RECHECK_RELEASE", "RELEASE_UNCONFIRMED", "RELEASE_NOT_CONFIRMED",
            hold, intent,
        )
    return _out(
        "ESCALATE", "RELEASE_UNCONFIRMED", "RELEASE_NOT_CONFIRMED",
        hold, intent, notify=True,
    )


def _collect(v, hold, intent):
    if v["sha_mismatch"] > 0:
        if v["download_retries_used"] < v["download_retry_limit"]:
            return _out("COLLECT", "COLLECTING", "SHA_MISMATCH", hold, intent)
        return _out(
            "ESCALATE", "BLOCKED", "SHA_MISMATCH", hold, intent, notify=True,
        )
    if v["pending_download"] > 0:
        return _out("COLLECT", "COLLECTING", "COLLECT_PENDING", hold, intent)
    return _out("RELEASE", "RELEASING", "OUTPUTS_VERIFIED", hold, intent)


def _saving(v, hold, intent):
    if v["saved"]:
        return _out("COLLECT", "COLLECTING", "SAVE_CONFIRMED", hold, intent)
    if v["limit"]:
        return _limit(v, hold)
    return _out("WAIT", "SAVING", "SAVE_PENDING", hold, intent)


def _running(v, hold):
    if v["limit"]:
        return _limit(v, hold)
    cap = v["cu_cap"]
    if v["cu_used"] >= v["cu_soft_ratio"] * cap:
        return _out("REQUEST_SAVE", "SAVING", "CU_SOFT_CAP", hold, "pause")
    if v["elapsed_minutes"] >= v["max_minutes"] - v["save_before_max_minutes"]:
        return _out("REQUEST_SAVE", "SAVING", "MAX_TIME_SOON", hold, "pause")
    if v["now"] - v["last_advanced_at"] > v["stall_minutes"]:
        return _out(
            "COLLECT", "COLLECTING", "STALLED", hold, "fail", risk=(not v["saved"]),
        )
    if v["done_signal"]:
        if v["saved"]:
            return _out("COLLECT", "COLLECTING", "COMPLETE", hold, "finish")
        return _out("REQUEST_SAVE", "SAVING", "COMPLETE_SAVING", hold, "finish")
    return None


def decide(snapshot, contract, policy, now):
    v = _validate(snapshot, contract, policy, now)
    state = v["state"]
    hold = v["human_hold"]
    intent = v["stop_intent"]

    if state in _TERMINAL:
        return _out("WAIT", state, "TERMINAL", hold, intent)

    if v["human_command"] != "none":
        return _human(v, hold, intent)

    if v["bot_request"] != "none":
        return _bot(v, hold, intent)

    if v["host"] == "just_booted" and state != "RECONCILING":
        return _out("RECONCILE", "RECONCILING", "BOOT_RECONCILE", hold, intent)

    if state == "RECONCILING":
        return _reconcile(v, hold, intent)

    if v["host"] == "shutting_down":
        shutdown = _shutdown(v, hold, intent)
        if shutdown is not None:
            return shutdown

    if state in _PROBED and v["probe_status"] != "ok":
        return _probe_uncertain(v, hold, intent)

    if state == "UNKNOWN":
        return _unknown(v, hold, intent)

    if state in ("RELEASING", "RELEASE_UNCONFIRMED"):
        return _release_check(v, hold, intent)

    if state == "COLLECTING":
        return _collect(v, hold, intent)

    if state == "SAVING":
        return _saving(v, hold, intent)

    if state == "RUNNING":
        running = _running(v, hold)
        if running is not None:
            return running

    return _out("CONTINUE", state, "OK", hold, intent)
