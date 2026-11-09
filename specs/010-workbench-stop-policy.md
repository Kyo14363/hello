# Work order 010 - 工作台停機決策純函式（切片 ②）

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-11-09 JST）。本 PR **只含這份 spec**；閘門、鎖、實作各自後續 PR |
| Repo | https://github.com/Kyo14363/hello （程式放子目錄 `workbench/`） |
| Upstream | 009 `specs/009-local-workbench.md` 第 2、3、4 節與第 7 節切片 ②。與 001～008 互不相依，不 import `src/` 任何模組 |
| Implementer | spec **Clau小羊**；閘門與鎖 **Gpt小豬**；實作 **Gemi小狗**（Cursor 雲端 agent）；驗收與合併 **Gro小貓** |
| expected_paths | `specs/010-workbench-stop-policy.md`、`tools/check_010.py`、`workbench/stop_policy.py`、`workbench/tests/test_stop_policy.py`、`workbench/fixtures/scenarios.json` |
| Definition of done | 見下方「Definition of done」各條，全部可由程式判定 |

> ⚠ 本檔刻意**不放** `expected_paths` 表格列。`tools/ci_run_gates.py` 的 `discover()` 一看到 spec 表格裡有 `expected_paths` 列，就要求 `tools/check_010.py` 已存在，否則 `CI GATE ERROR`（exit 2）。本 PR 不含閘門，所以 `expected_paths` 先寫在下面的清單；**閘門 PR（Gpt小豬）要把它移進上方表格成一列**，並在 lock 記 010 的 initial acceptance。做法與 008 相同（008 spec PR #62 → 閘門 PR #63 → 實作 PR #65）。

本檔所有 CU（運算單位）、時間與步數都是**假資料**，不代表任何真實額度。

## expected_paths（閘門 PR 時移進表格）

閘門 PR 在上方表格加一列：第一格寫 `expected_paths`，第二格依序列出下面五個路徑，各自用反引號包住、以「、」分隔（與 007、008 同格式）。`ci_run_gates.py` 以完全相同的字串比對，不支援萬用字元。

實作 PR 的 diff 只能落在後三個檔。**不需要** `workbench/__init__.py` 或 `workbench/tests/__init__.py`：測試指令用 `PYTHONPATH=workbench` 加 `unittest discover -s workbench/tests`，與 007、008 的 `src/`、`tests/` 一樣沒有套件檔。多加任何檔都會讓 CI `scope: FAIL`。

## 要做的事

1. 新增 `workbench/stop_policy.py`，提供純函式 `decide(snapshot, contract, policy, now)`，回傳一個 dict（見 R3）。
2. 新增 `workbench/fixtures/scenarios.json`，內容是 R4 的 base 與 R5 對照表逐列轉成 JSON（假資料）。
3. 新增 `workbench/tests/test_stop_policy.py`，用 fixture 逐列測 `decide`，再加專門的斷言（見 R9）。

只有這三個新檔，不改任何既有檔。

## 規則

### R1 時間與數字

- 所有時間都是**假時間軸上的分鐘數**（int 或 float），`now` 由呼叫端傳入。函式不讀系統時鐘。
- 所有比較照 R6 寫的運算子，邊界值依 R6 處理，不另加誤差容忍。

### R2 輸入

`snapshot`、`contract`、`policy` 都是 dict，形狀與 R4 的 base 相同。`decide` 只讀下表列出的鍵；base 裡其他鍵（例如 `job_id`、`template_id`、`job_type`、`progress.value`、`checkpoint.confirmed_at`、`queue_empty`）可以存在但**不得影響結果**。

| 鍵 | 型別／允許值 | 意義 |
|---|---|---|
| `snapshot.state` | 009 §2.1 的 15 個狀態碼 | 目前狀態 |
| `snapshot.probe.status` | `ok`／`failed`／`timeout` | 最近一次查詢結果 |
| `snapshot.probe.consecutive_failures` | int | 連續失敗次數 |
| `snapshot.progress.last_advanced_at` | 分鐘 | step／批次上次前進的時間 |
| `snapshot.checkpoint.step` | int 或 null | 最後確認的 step（批次型為批次號） |
| `snapshot.checkpoint.confirmed` | bool | 最後 checkpoint 是否已回讀確認 |
| `snapshot.outputs.unsaved` | int | 已產生但尚未保存的單位數 |
| `snapshot.outputs.pending_download` | int | 已保存在遠端、尚未下載驗證的單位數 |
| `snapshot.outputs.first_unverified` | int 或 null | 第一個未下載驗證的單位編號 |
| `snapshot.outputs.sha_mismatch` | int | sha256 不符的檔數 |
| `snapshot.outputs.download_retries_used` | int | 已用的重新下載次數 |
| `snapshot.cu_used` | 數字 | 已用 CU（假資料） |
| `snapshot.elapsed_minutes` | 數字 | 已執行分鐘 |
| `snapshot.limit_hit_at` | 分鐘或 null | 第一次碰到 CU 硬上限或最長時間的時間；null 視為「剛碰到」 |
| `snapshot.unknown_since` | 分鐘或 null | 進入 `UNKNOWN` 的時間 |
| `snapshot.human_command` | `none`／`stop_after_save`／`stop_now`／`pause`／`resume` | 人工指令 |
| `snapshot.bot_request` | `none`／`pause`／`resume` | Bot 請求（`submit_job` 在端口登記時處理，不經 `decide`） |
| `snapshot.human_hold` | bool | 人工鎖 |
| `snapshot.stop_intent` | `none`／`pause`／`finish`／`fail` | 這次收尾最後要去哪（暫停、完成、失敗） |
| `snapshot.host` | `online`／`shutting_down`／`just_booted` | 本機狀態 |
| `snapshot.remote` | `running`／`finished`／`released`／`unreachable` | 遠端狀態（核對時用；切片 ④前一律是模擬值） |
| `snapshot.release_check` | `not_started`／`confirmed_zero`／`active_nonzero`／`check_failed` | 釋放回查結果 |
| `snapshot.release_retries_used` | int | 已用的釋放回查次數 |
| `snapshot.done_signal` | bool | 工作自報完成 |
| `contract.workload_kind` | `training`／`batch_inference` | 決定續跑點從哪裡取 |
| `contract.cu_cap` | 數字 | CU 硬上限（假資料） |
| `contract.cu_soft_ratio` | 數字 | 軟上限比例 |
| `contract.max_minutes` | 數字 | 最長執行時間 |
| `contract.heartbeat.stall_minutes` | 數字 | 停滯門檻 |
| `contract.on_host_offline` | `pause_safely`／`continue_until_checkpoint` | 本機關機時遠端工作怎麼辦 |
| `contract.submitted_by` | `human` 或 `bot:<名稱>` | 提交者 |
| `policy.probe_confirm_count` | int | 失聯確認次數 |
| `policy.unknown_alert_minutes` | 數字 | `UNKNOWN` 多久後轉人處理 |
| `policy.budget_conflict_mode` | `A`／`B`／`C` | 硬停與保進度衝突時的模式（009 §4.4） |
| `policy.grace_cu_ratio` | 數字 | 模式 C 寬限：`cu_cap` 的比例 |
| `policy.grace_minutes` | 數字 | 模式 C 寬限：分鐘 |
| `policy.save_before_max_minutes` | 數字 | 最長時間到前多少分鐘先要求保存 |
| `policy.download_retry_limit` | int | sha256 不符最多重新下載幾次 |
| `policy.release_recheck_limit` | int | 釋放回查最多幾次 |

009 §3 的 `save_grace_cu`／`save_grace_minutes` 由本單改成 policy 參數 `grace_cu_ratio`／`grace_minutes`，預設 0.1 與 15（取 `cu_cap` 的 10% 與 15 分鐘，先到者），之後改預設只要改 policy，不用改程式。

**驗證**：上表任何一個鍵缺少，或列舉值不在允許值內，`decide` 一律 `raise ValueError`（不是 `KeyError`）。

### R3 輸出

回傳一個 dict，鍵剛好是下面 9 個，不多不少：

| 鍵 | 型別 | 說明 |
|---|---|---|
| `action` | str | `CONTINUE`、`WAIT`、`REQUEST_SAVE`、`COLLECT`、`RELEASE`、`RECHECK_RELEASE`、`RECONCILE`、`MARK_UNKNOWN`、`ESCALATE`、`REJECT_REQUEST`、`CLOSE` 之一 |
| `next_state` | str | 建議的下一狀態（009 §2.1 狀態碼） |
| `reason_code` | str | 見 R5 表與 R6 |
| `ui_message` | str | 給人看的中文一句話，非空；閘門只驗非空，不比對內容 |
| `data_at_risk` | bool | 這個動作是否可能讓未保存或未下載的產出遺失 |
| `notify_human` | bool | 是否要主動通知人 |
| `human_hold_after` | bool | 這次決定之後人工鎖的值 |
| `stop_intent` | str | 這次決定之後的收尾去向 |
| `from_unit` | int 或 null | 從哪一個 step／批次開始收或續跑；只有核對（R6 第 5 條）的收產出與暫停會填，其他一律 null |

`CLOSE` 是本單在 009 §4.3 之外新增的動作：資源已確認 0 active，進入 `PAUSED`／`DONE`／`FAILED`。

除非某條規則另寫，`human_hold_after` 等於 `snapshot.human_hold`，`stop_intent` 等於 `snapshot.stop_intent`，`data_at_risk` 與 `notify_human` 為 false，`from_unit` 為 null。

### R4 base（假資料）

R5 每一列都是「base 深拷貝後，套用該列 `set`」得到輸入，再呼叫 `decide(snapshot, contract, policy, now)`。`set` 的鍵是以 `.` 分隔的路徑，前綴 `snapshot.`／`contract.`／`policy.` 指向對應的 dict；路徑必須已經存在於 base，不得新增鍵。本表沒有任何一列改 `now`。

```json
{
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
}
```

### R5 對照表（閘門逐列比對，`==` 完全相等，`ui_message` 除外）

`T01`～`T21` 對應 009 §4.5 的情境；一條情境要兩步時拆成 a／b（T09b 另測「寬限分鐘先到」）。`U01`、`P01`、`P02` 補「狀態不明撞上限」與「人與 Bot 的優先」，`E01`、`E02` 是輸入驗證。表內的值以 JSON 解讀（`true`／`false`／`null`；`set` 欄的字串帶雙引號）。

| # | 情境 | `set`（相對 base） | action | next_state | reason_code | data_at_risk | notify_human | human_hold_after | stop_intent | from_unit |
|---|---|---|---|---|---|---|---|---|---|---|
| T01 | 查詢單次失敗 | `snapshot.probe.status`=`"failed"`；`snapshot.probe.consecutive_failures`=`1` | `WAIT` | `RUNNING` | `PROBE_RETRY` | `false` | `false` | `false` | `none` | `null` |
| T02 | 查詢連續失敗達門檻 | `snapshot.probe.status`=`"timeout"`；`snapshot.probe.consecutive_failures`=`3` | `MARK_UNKNOWN` | `UNKNOWN` | `PROBE_UNCERTAIN` | `false` | `false` | `false` | `none` | `null` |
| T03 | 狀態不明過久 | `snapshot.state`=`"UNKNOWN"`；`snapshot.probe.status`=`"failed"`；`snapshot.probe.consecutive_failures`=`5`；`snapshot.unknown_since`=`960` | `ESCALATE` | `BLOCKED` | `UNKNOWN_TOO_LONG` | `false` | `true` | `false` | `none` | `null` |
| T04 | 心跳停滯 | `snapshot.progress.last_advanced_at`=`975` | `COLLECT` | `COLLECTING` | `STALLED` | `false` | `false` | `false` | `fail` | `null` |
| T05 | 程序活著且剛前進 | `snapshot.progress.last_advanced_at`=`1000` | `CONTINUE` | `RUNNING` | `OK` | `false` | `false` | `false` | `none` | `null` |
| T06 | 預算軟上限 | `snapshot.cu_used`=`8` | `REQUEST_SAVE` | `SAVING` | `CU_SOFT_CAP` | `false` | `false` | `false` | `pause` | `null` |
| T07 | 硬上限且已保存 | `snapshot.cu_used`=`10`；`snapshot.limit_hit_at`=`1000` | `COLLECT` | `COLLECTING` | `CU_HARD_CAP` | `false` | `false` | `false` | `pause` | `null` |
| T08 | 硬上限未保存，C 寬限內 | `snapshot.cu_used`=`10.5`；`snapshot.limit_hit_at`=`995`；`snapshot.outputs.unsaved`=`2` | `REQUEST_SAVE` | `SAVING` | `CU_HARD_CAP_UNSAVED` | `false` | `false` | `false` | `pause` | `null` |
| T09 | 硬上限未保存，C 寬限 CU 用完 | `snapshot.cu_used`=`11.1`；`snapshot.limit_hit_at`=`995`；`snapshot.outputs.unsaved`=`2` | `RELEASE` | `RELEASING` | `CU_GRACE_EXHAUSTED` | `true` | `true` | `false` | `pause` | `null` |
| T09b | 硬上限未保存，C 寬限分鐘先到 | `snapshot.cu_used`=`10.2`；`snapshot.limit_hit_at`=`985`；`snapshot.outputs.unsaved`=`2` | `RELEASE` | `RELEASING` | `CU_GRACE_EXHAUSTED` | `true` | `true` | `false` | `pause` | `null` |
| T10a | 同 T08，模式 A | `snapshot.cu_used`=`10.5`；`snapshot.limit_hit_at`=`995`；`snapshot.outputs.unsaved`=`2`；`policy.budget_conflict_mode`=`"A"` | `RELEASE` | `RELEASING` | `CU_HARD_CAP_UNSAVED` | `true` | `true` | `false` | `pause` | `null` |
| T10b | 同 T09，模式 B（無上限等保存） | `snapshot.cu_used`=`11.1`；`snapshot.limit_hit_at`=`985`；`snapshot.outputs.unsaved`=`2`；`policy.budget_conflict_mode`=`"B"` | `REQUEST_SAVE` | `SAVING` | `CU_HARD_CAP_UNSAVED` | `false` | `false` | `false` | `pause` | `null` |
| T11 | 人搶停 Bot 的工作 | `contract.submitted_by`=`"bot:demo"`；`snapshot.human_command`=`"stop_after_save"` | `REQUEST_SAVE` | `SAVING` | `HUMAN_STOP` | `false` | `false` | `true` | `pause` | `null` |
| T12 | Bot 續跑有人工鎖的工作 | `contract.submitted_by`=`"bot:demo"`；`snapshot.state`=`"PAUSED"`；`snapshot.human_hold`=`true`；`snapshot.bot_request`=`"resume"` | `REJECT_REQUEST` | `PAUSED` | `HUMAN_HOLD` | `false` | `false` | `true` | `none` | `null` |
| T13 | 人工立即停止，有未保存 | `snapshot.human_command`=`"stop_now"`；`snapshot.outputs.unsaved`=`1` | `RELEASE` | `RELEASING` | `HUMAN_STOP` | `true` | `false` | `true` | `pause` | `null` |
| T14a | 本機正常關機、遠端在跑 | `snapshot.host`=`"shutting_down"` | `REQUEST_SAVE` | `SAVING` | `HOST_SHUTDOWN` | `false` | `false` | `false` | `pause` | `null` |
| T14b | 關機收尾：釋放已確認 | `snapshot.host`=`"shutting_down"`；`snapshot.state`=`"RELEASING"`；`snapshot.release_check`=`"confirmed_zero"`；`snapshot.stop_intent`=`"pause"` | `CLOSE` | `PAUSED` | `RELEASE_CONFIRMED` | `false` | `false` | `false` | `none` | `null` |
| T15a | 開機：先核對 | `snapshot.host`=`"just_booted"` | `RECONCILE` | `RECONCILING` | `BOOT_RECONCILE` | `false` | `false` | `false` | `none` | `null` |
| T15b | 開機核對：遠端已釋放，從 step 300 續 | `snapshot.host`=`"just_booted"`；`snapshot.state`=`"RECONCILING"`；`snapshot.remote`=`"released"`；`snapshot.progress.value`=`300`；`snapshot.checkpoint.step`=`300` | `CLOSE` | `PAUSED` | `RECONCILED_PAUSED` | `false` | `false` | `false` | `none` | `300` |
| T16 | 開機核對：遠端查不到 | `snapshot.host`=`"just_booted"`；`snapshot.state`=`"RECONCILING"`；`snapshot.remote`=`"unreachable"`；`snapshot.probe.status`=`"failed"`；`snapshot.probe.consecutive_failures`=`1` | `MARK_UNKNOWN` | `UNKNOWN` | `PROBE_UNCERTAIN` | `false` | `true` | `false` | `none` | `null` |
| T17a | 開機核對：批次 23～25 未下載、遠端可取 | `contract.workload_kind`=`"batch_inference"`；`contract.job_type`=`"J1"`；`snapshot.state`=`"RECONCILING"`；`snapshot.remote`=`"finished"`；`snapshot.outputs.pending_download`=`3`；`snapshot.outputs.first_unverified`=`23` | `COLLECT` | `COLLECTING` | `RECONCILED_COLLECT` | `false` | `false` | `false` | `none` | `23` |
| T17b | 開機核對：批次 23～25 未下載、遠端已釋放 | `contract.workload_kind`=`"batch_inference"`；`contract.job_type`=`"J1"`；`snapshot.state`=`"RECONCILING"`；`snapshot.remote`=`"released"`；`snapshot.outputs.pending_download`=`3`；`snapshot.outputs.first_unverified`=`23` | `CLOSE` | `PAUSED` | `RECONCILED_PAUSED` | `true` | `true` | `false` | `none` | `23` |
| T18a | sha256 不符，重試未用完 | `snapshot.state`=`"COLLECTING"`；`snapshot.outputs.sha_mismatch`=`1`；`snapshot.outputs.download_retries_used`=`1` | `COLLECT` | `COLLECTING` | `SHA_MISMATCH` | `false` | `false` | `false` | `none` | `null` |
| T18b | sha256 不符，重試用完 | `snapshot.state`=`"COLLECTING"`；`snapshot.outputs.sha_mismatch`=`1`；`snapshot.outputs.download_retries_used`=`3` | `ESCALATE` | `BLOCKED` | `SHA_MISMATCH` | `false` | `true` | `false` | `none` | `null` |
| T19a | 釋放後回查非 0 | `snapshot.state`=`"RELEASING"`；`snapshot.release_check`=`"active_nonzero"`；`snapshot.stop_intent`=`"finish"` | `RECHECK_RELEASE` | `RELEASE_UNCONFIRMED` | `RELEASE_NOT_CONFIRMED` | `false` | `false` | `false` | `finish` | `null` |
| T19b | 釋放回查次數用完 | `snapshot.state`=`"RELEASE_UNCONFIRMED"`；`snapshot.release_check`=`"check_failed"`；`snapshot.release_retries_used`=`3`；`snapshot.stop_intent`=`"finish"` | `ESCALATE` | `RELEASE_UNCONFIRMED` | `RELEASE_NOT_CONFIRMED` | `false` | `true` | `false` | `finish` | `null` |
| T20 | 佇列空但訓練仍在前進 | `snapshot.queue_empty`=`true` | `CONTINUE` | `RUNNING` | `OK` | `false` | `false` | `false` | `none` | `null` |
| T21 | 最長時間到、checkpoint 2 分鐘前確認 | `snapshot.elapsed_minutes`=`120`；`snapshot.checkpoint.confirmed_at`=`998` | `COLLECT` | `COLLECTING` | `MAX_TIME` | `false` | `false` | `false` | `pause` | `null` |
| U01 | 狀態不明時撞硬上限且寬限用完 | `snapshot.state`=`"UNKNOWN"`；`snapshot.probe.status`=`"failed"`；`snapshot.probe.consecutive_failures`=`4`；`snapshot.unknown_since`=`995`；`snapshot.cu_used`=`11.1`；`snapshot.limit_hit_at`=`990` | `ESCALATE` | `BLOCKED` | `CU_HARD_CAP_UNKNOWN` | `false` | `true` | `false` | `none` | `null` |
| P01 | Bot 請求暫停人提交的工作 | `snapshot.bot_request`=`"pause"` | `REQUEST_SAVE` | `SAVING` | `BOT_PAUSE` | `false` | `false` | `false` | `pause` | `null` |
| P02 | 人與 Bot 同時下令，以人為準 | `contract.submitted_by`=`"bot:demo"`；`snapshot.human_command`=`"stop_after_save"`；`snapshot.bot_request`=`"resume"` | `REQUEST_SAVE` | `SAVING` | `HUMAN_STOP` | `false` | `false` | `true` | `pause` | `null` |
| E01 | 未知狀態值 | `snapshot.state`=`"IDLE"` | `raise ValueError` | — | — | — | — | — | — | — |
| E02 | 未知衝突模式 | `policy.budget_conflict_mode`=`"D"` | `raise ValueError` | — | — | — | — | — | — | — |

### R6 判斷順序（先符合者先決定，後面不再看）

以下記號：
- `saved` = `checkpoint.confirmed` 為 true 且 `outputs.unsaved == 0`。
- `hard` = `cu_used >= cu_cap`；`timeup` = `elapsed_minutes >= max_minutes`；`limit` = `hard or timeup`。
- `over` = `now - limit_hit_at`（`limit_hit_at` 為 null 時取 0）。
- `grace_out` = `cu_used >= cu_cap + cu_cap * grace_cu_ratio` **或** `over >= grace_minutes`（兩者先到者）。
- `PROBED` = {`STARTING`, `RUNNING`, `SAVING`, `COLLECTING`, `RELEASING`, `RELEASE_UNCONFIRMED`, `BLOCKED`}。

0. **驗證**：見 R2，不合即 `raise ValueError`。
1. **終態**：`state` 是 `DONE`／`FAILED`／`CANCELLED` → `WAIT`，next 同 `state`，`TERMINAL`。
2. **人工指令**（先於一切非終態規則）：
   - `stop_now` → `RELEASE`／`RELEASING`／`HUMAN_STOP`；`data_at_risk` = `not saved or pending_download > 0`；`human_hold_after=true`；`stop_intent=pause`。不受查詢狀態影響（009 §2.5 唯一可在 `UNKNOWN` 釋放的路徑）。
   - `stop_after_save` → `REQUEST_SAVE`／`SAVING`／`HUMAN_STOP`；`pause` → 同上但 reason `HUMAN_PAUSE`。兩者都 `human_hold_after=true`、`stop_intent=pause`。
   - `resume`：`state == PAUSED` → `CONTINUE`／`QUEUED`／`HUMAN_RESUME`，`human_hold_after=false`（只有人能解鎖），`stop_intent=none`；否則 `REJECT_REQUEST`，next 同 `state`，`BAD_STATE`。
   - 人工指令不是 `none` 時，`bot_request` 一律不看（人與 Bot 同時下令以人為準）。
3. **Bot 請求**（`bot_request != none`）：
   - `human_hold` 為 true → `REJECT_REQUEST`，next 同 `state`，`HUMAN_HOLD`。
   - `pause`：`state == RUNNING` → `REQUEST_SAVE`／`SAVING`／`BOT_PAUSE`，`stop_intent=pause`（只走保存後暫停，Bot 沒有立即停）；否則 `REJECT_REQUEST`／`BAD_STATE`。
   - `resume`：`state != PAUSED` → `REJECT_REQUEST`／`BAD_STATE`；`submitted_by` 不是 `bot:` 開頭 → `REJECT_REQUEST`／`NOT_OWNER`；否則 `CONTINUE`／`QUEUED`／`BOT_RESUME`，`stop_intent=none`。（009 §6.1 待決，本單採建議值：Bot 只能續跑自己提交且無人工鎖的工作。）
4. **剛開機**：`host == just_booted` 且 `state != RECONCILING` → `RECONCILE`／`RECONCILING`／`BOOT_RECONCILE`。
5. **核對中**（`state == RECONCILING`）：
   - `probe.status != ok` 或 `remote == unreachable` → `MARK_UNKNOWN`／`UNKNOWN`／`PROBE_UNCERTAIN`，`notify_human=true`（不重啟、不釋放）。
   - `remote == running` → `CONTINUE`／`RUNNING`／`RECONCILED_RUNNING`。
   - `remote == finished` 且 `pending_download > 0` → `COLLECT`／`COLLECTING`／`RECONCILED_COLLECT`，`from_unit = first_unverified`（已驗過的批次不重收）。
   - `remote == finished` 且 `pending_download == 0` → `RELEASE`／`RELEASING`／`RECONCILED_RELEASE`。
   - `remote == released`：
     - `training`：`checkpoint.confirmed` → `CLOSE`／`PAUSED`／`RECONCILED_PAUSED`，`from_unit = checkpoint.step`（不從 0 重跑）；未確認 → `ESCALATE`／`BLOCKED`／`RECONCILE_CONFLICT`，`notify_human=true`。
     - `batch_inference` → `CLOSE`／`PAUSED`／`RECONCILED_PAUSED`，`from_unit = first_unverified`；`pending_download > 0` 時 `data_at_risk=true`、`notify_human=true`（遠端已釋放，未下載的批次遺失，要從該批重排）。
6. **本機即將關機**（`host == shutting_down`）：
   - `state` 是 `REGISTERED`／`QUEUED` → `WAIT`，next 同 `state`，`HOST_SHUTDOWN`（不啟動新工作）。
   - `state` 是 `STARTING`／`RUNNING`：`on_host_offline == pause_safely` → `REQUEST_SAVE`／`SAVING`／`HOST_SHUTDOWN`，`stop_intent=pause`；否則 `CONTINUE`，next 同 `state`，`HOST_OFFLINE_REMOTE_RUNNING`，`notify_human=true`。
   - 其他狀態不在這裡決定，往下走。
7. **查詢不確定**（`state` 在 `PROBED` 且 `probe.status != ok`）：`consecutive_failures < probe_confirm_count` → `WAIT`，next 同 `state`，`PROBE_RETRY`；否則 `MARK_UNKNOWN`／`UNKNOWN`／`PROBE_UNCERTAIN`。
8. **狀態不明**（`state == UNKNOWN`），依序：
   - `hard and grace_out` → `ESCALATE`／`BLOCKED`／`CU_HARD_CAP_UNKNOWN`，`notify_human=true`（不自動停，交給人）。
   - `unknown_since` 非 null 且 `now - unknown_since >= unknown_alert_minutes` → `ESCALATE`／`BLOCKED`／`UNKNOWN_TOO_LONG`，`notify_human=true`。
   - `probe.status == ok` → `RECONCILE`／`RECONCILING`／`PROBE_RECOVERED`。
   - 其他 → `WAIT`／`UNKNOWN`／`PROBE_UNCERTAIN`。
9. **釋放回查**（`state` 是 `RELEASING`／`RELEASE_UNCONFIRMED`）：
   - `confirmed_zero` → `CLOSE`／`RELEASE_CONFIRMED`；next 依 `stop_intent`：`finish` → `DONE`，`fail` → `FAILED`，`pause` 或 `none` → `PAUSED`；`stop_intent` 變 `none`。
   - `not_started` → `WAIT`，next 同 `state`，`RELEASE_PENDING`。
   - `active_nonzero`／`check_failed`：`release_retries_used < release_recheck_limit` → `RECHECK_RELEASE`／`RELEASE_UNCONFIRMED`／`RELEASE_NOT_CONFIRMED`；否則 `ESCALATE`／`RELEASE_UNCONFIRMED`／`RELEASE_NOT_CONFIRMED`，`notify_human=true`（009 §4.4 第 5 條：停在釋放未確認，不顯示完成）。
10. **收產出**（`state == COLLECTING`）：
    - `sha_mismatch > 0`：`download_retries_used < download_retry_limit` → `COLLECT`／`COLLECTING`／`SHA_MISMATCH`（重新下載）；否則 `ESCALATE`／`BLOCKED`／`SHA_MISMATCH`，`notify_human=true`。
    - `pending_download > 0` → `COLLECT`／`COLLECTING`／`COLLECT_PENDING`。
    - 其他 → `RELEASE`／`RELEASING`／`OUTPUTS_VERIFIED`。
11. **保存中**（`state == SAVING`）：`saved` → `COLLECT`／`COLLECTING`／`SAVE_CONFIRMED`；否則 `limit` → 走「上限處理」；否則 `WAIT`／`SAVING`／`SAVE_PENDING`。
12. **執行中**（`state == RUNNING`），依序：
    - `limit` → 走「上限處理」。
    - `cu_used >= cu_soft_ratio * cu_cap` → `REQUEST_SAVE`／`SAVING`／`CU_SOFT_CAP`，`stop_intent=pause`。
    - `elapsed_minutes >= max_minutes - save_before_max_minutes` → `REQUEST_SAVE`／`SAVING`／`MAX_TIME_SOON`，`stop_intent=pause`。
    - `now - progress.last_advanced_at > stall_minutes` → `COLLECT`／`COLLECTING`／`STALLED`，`data_at_risk = not saved`，`stop_intent=fail`（收已保存的產出後釋放）。
    - `done_signal`：`saved` → `COLLECT`／`COLLECTING`／`COMPLETE`；否則 `REQUEST_SAVE`／`SAVING`／`COMPLETE_SAVING`；兩者 `stop_intent=finish`。
13. **其他** → `CONTINUE`，next 同 `state`，`OK`。佇列是否為空（`queue_empty`）不是判斷依據（T20）。

**上限處理**（11、12 共用；`stop_intent` 一律設 `pause`）：
- `saved` → `COLLECT`／`COLLECTING`；reason：`hard` 為 `CU_HARD_CAP`，否則 `MAX_TIME`。`data_at_risk=false`。
- 未 `saved`，reason 先定為：`hard` 時 `CU_HARD_CAP_UNSAVED`，否則 `MAX_TIME_UNSAVED`，再依模式：
  - **A 硬停優先** → `RELEASE`／`RELEASING`／（上述 reason），`data_at_risk=true`，`notify_human=true`。
  - **B 保進度優先** → `REQUEST_SAVE`／`SAVING`／（上述 reason），不設上限。
  - **C 有限寬限（預設，2026-11-09 定案）**：`grace_out` 為 false → `REQUEST_SAVE`／`SAVING`／（上述 reason）；為 true → `RELEASE`／`RELEASING`／`CU_GRACE_EXHAUSTED`，`data_at_risk=true`，`notify_human=true`。

**硬性保證**（閘門會另外掃）：人工指令為 `none` 時，任何 `probe.status != ok` 的輸入都不會得到 `RELEASE` 或 `CLOSE`，next 也不會變成 `DONE`／`FAILED`／`PAUSED`／`CANCELLED`／`RELEASING`（next 等於原 `state` 不算）。

### R7 寫法限制

- `workbench/stop_policy.py` 只用標準庫。允許的 import 只有 `copy`、`math`、`numbers`、`typing`、`dataclasses`、`enum`、`types`、`collections`；其他一律不准（特別是 `os`、`sys`、`io`、`pathlib`、`shutil`、`tempfile`、`socket`、`ssl`、`http`、`urllib`、`subprocess`、`time`、`datetime`、`random`、`json`、`logging`、`importlib`）。
- 不呼叫 `open`、`print`、`input`、`eval`、`exec`、`compile`、`__import__`、`globals`、`setattr`。
- 不改輸入：呼叫前後 `snapshot`、`contract`、`policy` 深比較相等。
- 同一輸入呼叫兩次，結果相等。
- 模組頂層有 `def decide(snapshot, contract, policy, now):`，剛好四個位置參數、沒有預設值、沒有 `*args`／`**kwargs`。可另加私有輔助函式與常數。import 時不得有輸出。
- 三個新檔都不得含 `http://`、`https://`、電子郵件地址、絕對路徑（`/` 開頭的檔案路徑或磁碟機代號）、token 樣式字串。

### R8 fixture 格式（`workbench/fixtures/scenarios.json`）

```json
{
  "schema": 1,
  "base": { "now": 1000, "snapshot": {}, "contract": {}, "policy": {} },
  "scenarios": [
    { "id": "T01", "title": "查詢單次失敗", "set": { "snapshot.probe.status": "failed" }, "expect": { "action": "WAIT" } }
  ]
}
```

（上面只示意形狀，`{}` 與單鍵 `set`／`expect` 都是省略寫法。）

- 頂層鍵剛好 `schema`、`base`、`scenarios`；`schema` 為 1。
- `base` 與 R4 完全相等。
- `scenarios` 依 R5 的列順序，每列一個物件，鍵剛好 `id`、`title`、`set`、`expect`。`id` 與 `set` 與 R5 相等；`title` 自由填寫（建議照表）。
- 一般列的 `expect` 鍵剛好是 R3 去掉 `ui_message` 的 8 個鍵，值與 R5 相等；`E01`、`E02` 的 `expect` 是 `{"raises": "ValueError"}`。
- UTF-8，不得有重複鍵。

### R9 測試

- `workbench/tests/test_stop_policy.py` 用標準庫 `unittest`，不引 pytest、不加 pip 依賴；用 `from stop_policy import decide`（模組層 import）。
- fixture 路徑由測試檔自己的位置推出（`workbench/fixtures/scenarios.json`），不寫絕對路徑。測試可以讀檔，`stop_policy.py` 不可以。
- repo 根跑 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workbench python -m unittest discover -s workbench/tests` 退出 0，跑到的測試數 ≥ 10。
- 至少要有：
  1. 一個測試逐列跑 fixture 每一列（建議 `subTest`），比對 8 個鍵並驗 `ui_message` 為非空 str；`E01`、`E02` 用 `assertRaises(ValueError)`。
  2. 一個測試專門斷言查詢失敗組（`T01`、`T02`、`T03`、`T16`、`U01`）的 `action` 不是 `RELEASE`／`CLOSE`，next 不是 `DONE`。
  3. 人工鎖：`T12` 回 `REJECT_REQUEST`＋`HUMAN_HOLD`；`P02` 人的指令勝過 Bot。
  4. 模式 C 寬限：`T08` 不釋放、`T09` 以 CU 用完釋放、`T09b` 以分鐘先到釋放。
  5. 不改輸入、同輸入同輸出。
  6. `queue_empty` 不影響結果（T20 與 T05 的 8 個鍵相同）。

## Definition of done（全部可機器判定）

1. `python tools/check_010.py` exit 0，最後一行 `RESULT: ALL PASS`。
2. 實作 PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠：選到 `010`、`scope: PASS`、`lock: PASS`、`CI RESULT: PASS`。
3. 實作 PR diff（相對 main，三點 diff）的檔案集合 == {`workbench/stop_policy.py`, `workbench/tests/test_stop_policy.py`, `workbench/fixtures/scenarios.json`}。
4. R9 指令 exit 0，跑到的測試數 ≥ 10。

## 閘門（給 Gpt小豬，本 PR 不寫）

`tools/check_010.py` 沿用 007、008 的寫法：標準庫、離線、ASCII stdout，子程序設 `PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`、自設 `PYTHONPATH=workbench`；活檔只讀，突變在暫存複本；每項印 `[PASS]`／`[FAIL]`／`[BLOCKED]`，結尾 `RESULT: ALL PASS` 或 `RESULT: FAIL`。建議項目：

- **G1 形狀與純度**：三檔存在；`ast` 確認 R7 的簽名、import 白名單、禁止呼叫；`import stop_policy` stdout 為空。
- **G2 fixture 對表**：閘門內建 R4 base 與 R5 表（從本 spec 抄成常數，不在執行時解析 spec），嚴格解析 `scenarios.json`（重複鍵即紅），與內建常數完全相等（`title` 除外）。
- **G3 行為逐列**：閘門自己用內建常數組輸入、呼叫 `decide`，逐列比 8 個鍵，`ui_message` 非空 str，`E01`、`E02` raise `ValueError`；每列呼叫前後輸入深比較不變、呼叫兩次結果相等；回傳 dict 的鍵集合剛好 9 個。
- **G4 查詢失敗掃描**：對 12 個非終態 `state` × `probe.status`（`failed`／`timeout`）× `consecutive_failures` 0～5 × `cu_used`（5、10、11.1、50）× 模式 A／B／C × `host` 三值，固定 `human_command=none`、`limit_hit_at=900`、`outputs.unsaved=2`、`release_check=check_failed`、`remote=unreachable`，斷言 R6「硬性保證」。共 12 × 2 × 6 × 4 × 3 × 3 = 5184 組。
- **G5 測試全綠**：R9 指令 exit 0，`Ran N tests` 的 N ≥ 10。
- **G6 突變必須紅**：在暫存複本的 `stop_policy.py` 尾端附加包裝函式重新定義 `decide`（不依賴實作內部寫法），每個突變都要讓 R9 指令 exit 非 0：
  - **M1 查詢失敗當閒置**：`probe.status != ok` 且 `human_command == none` 時直接回 `RELEASE`／`RELEASING`。
  - **M2 拿掉人工鎖**：`bot_request != none` 且 `human_hold` 為 true 時，把 `human_hold` 改成 false 再呼叫原函式（T12 會變成 `CONTINUE`／`QUEUED`）。
  - **M3 硬上限跳過寬限**：模式 `C` 改成 `A` 再呼叫原函式（T08 會變成 `RELEASE`）。
- **G7 公開 repo 衛生**：三檔不含 URL、電子郵件、絕對路徑、token 樣式字串。
- **G8 回歸與活檔不動**：`python tools/check_007.py`、`python tools/check_008.py` exit 0；前後對 repo 檔（略 `.git`、`__pycache__`）算 sha256 不變。

## 範圍與 PR 形狀（CI 會怎麼判）

`tools/ci_run_gates.py` 用**整張 PR 的 diff** 判範圍。

- **PR A（本 PR，spec only）**：只新增 `specs/010-workbench-stop-policy.md`。spec 沒有 `expected_paths` 表格列 → `discover()` 略過本檔；diff 不碰 001～008 的 `expected_paths` → regression 模式跑 001～008 全部閘門，應與 main 同為綠。lock 不動。已於 2026-11-09 JST 用 `--base main --head HEAD` 模擬。
- **PR B（閘門＋鎖，Gpt小豬）**：把 expected_paths 移進表格、加 `tools/check_010.py`、lock 加 010（三者同一張 PR）。預期選到 010、scope／lock PASS、`check_010` 紅（尚未實作，G1 紅、G8 綠）。
- **PR C（實作，Gemi小狗，PR B 合進 main 後才開）**：只新增三個 `workbench/` 檔。只 `git add` 這三檔並設 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 進 diff 造成 `scope: FAIL`。證據貼 PR 留言，不進 diff。

## 不做的事

- 不改 `src/`、`tests/`、`fixtures/`、`.github/`、`specs/001`～`009`。
- 不改 `tools/check_001.py`～`check_008.py`、`tools/ci_run_gates.py`，不改 lock 裡 001～008 的紀錄。
- 不做介面、伺服器、Bot 端口（切片 ③ 工單 011）；不接真遠端（切片 ④）。
- 不加 pytest 或任何 pip 依賴，不上網，不讀寫檔（測試讀 fixture 除外）。
- 不把 `gate` 設成 required（repo 設定由擁有者決定）。
