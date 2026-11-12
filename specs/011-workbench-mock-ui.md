# Work order 011 - 工作台假資料介面原型（切片 ③）

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-11-12 JST）。本 PR **只含這份 spec**；閘門、鎖、實作各自後續 PR |
| Repo | https://github.com/Kyo14363/hello （程式放子目錄 `workbench/`） |
| Upstream | 009 `specs/009-local-workbench.md` 第 2、5、6 節與第 7 節切片 ③；010 `workbench/stop_policy.py` 的 `decide`（已合併）。與 001～008 互不相依，不 import `src/` 任何模組 |
| Implementer | spec **Clau小羊**；閘門與鎖 **Gpt小豬**；實作 **Gemi小狗**（Cursor 雲端 agent）；驗收與合併 **Gro小貓** |
| Definition of done | 見下方「Definition of done」各條，全部可由程式判定 |

> ⚠ 本檔刻意**不放** `expected_paths` 表格列，閘門 PR 才把下方清單移進上方表格。做法與 008、010 相同（010：spec PR #67 → 閘門 PR #68 → 實作 PR #69）。

本檔所有 CU（運算單位）、時間、步數與雜湊都是**假資料**，不代表任何真實額度或真實檔案。

## expected_paths（閘門 PR 時移進表格）

閘門 PR 在上方表格加一列：第一格寫 `expected_paths`，第二格依序列出下面七個路徑，各自用反引號包住、以「、」分隔（與 007、008、010 同格式）。`ci_run_gates.py` 以完全相同的字串比對，不支援萬用字元。

1. `specs/011-workbench-mock-ui.md`
2. `tools/check_011.py`
3. `workbench/ui/index.html`
4. `workbench/ui/app.js`
5. `workbench/ui/style.css`
6. `workbench/ui/fixtures/jobs.json`
7. `workbench/serve_local.py`

實作 PR 的 diff 只能落在後五個檔。**不改** 010 的三個檔（`workbench/stop_policy.py`、`workbench/tests/test_stop_policy.py`、`workbench/fixtures/scenarios.json`），不加 `__init__.py`、不加測試檔（行為由 `check_011.py` 直接驗）。多加任何檔都會讓 CI `scope: FAIL`。

## 要做的事

1. 新增 `workbench/serve_local.py`：標準庫的本機伺服器，**只綁 `127.0.0.1`**。載入假資料、提供靜態頁與 JSON API；所有狀態轉移都呼叫 010 的 `stop_policy.decide`，不另寫決策規則。
2. 新增 `workbench/ui/fixtures/jobs.json`：假資料工作清單，涵蓋 009 §2.1 全部 15 個狀態。
3. 新增 `workbench/ui/index.html`、`workbench/ui/app.js`、`workbench/ui/style.css`：中文靜態頁，只向同源的 `/api/` 取資料，畫面元素照 009 §5。

## 範圍：做什麼、不做什麼

| 項目 | 本單 | 說明 |
|---|---|---|
| 15 狀態顯示 | 做 | 中文名照 009 §2.1；未知狀態碼顯示「狀態不明」並當忙（R2） |
| 人工指令（保存後停止、立即停止、暫停、續跑） | 做（只改記憶體裡的假資料） | 經 `decide`；立即停止要二次確認（R5） |
| 人工鎖 | 做 | 人工停止／暫停後 `human_hold=true`，Bot 請求一律被拒（`HUMAN_HOLD`），由 `decide` 判 |
| 系統推進一步（模擬） | 做 | `tick`：用目前假快照呼叫 `decide` 並套用結果 |
| 本機狀態切換（模擬） | 做 | 在線／即將關機／剛開機；只重算決策預覽，不自動轉移 |
| Bot 端口 `list_jobs`、`get_status` | 做（假資料） | 只回摘要，不回原始日誌 |
| Bot 端口 `request_pause` | 做（假資料） | 只走「保存後暫停」；有人工鎖即拒 |
| Bot 端口 `submit_job` | **明示不做** | 一律回 `accepted=false`、`NOT_IN_PROTOTYPE`；範本清單與參數上下限待擁有者決定（009 §8） |
| Bot 續跑、立即停止、釋放、改上限、解鎖、讀檔、執行指令 | **不做** | 端口回 `ACTION_NOT_ALLOWED`（009 §6.1） |
| 端口授權（009 §6.3 A～D） | **不做** | 待擁有者決定。本單不讀、不存、不收任何 token；請求帶憑證樣式欄位直接拒（R6） |
| 請求限速、跨機器呼叫通道 | **不做** | 切片 ④ 前不談 |
| 稽核紀錄 | 做（只在記憶體） | 不寫檔；重啟或 `reset` 即清空 |
| 接真 Colab、任何外部網路 | **不做** | 切片 ④，另批且需擁有者核准 |
| 寫檔、讀系統時鐘、讀環境變數 | **不做** | 時間一律用假資料的分鐘數 |

## 規則

### R1 檔案與執行方式

- 只用 Python 標準庫，不加 pip 依賴；前端不用任何外部函式庫、字型或 CDN。
- 從 repo 根啟動：`PYTHONDONTWRITEBYTECODE=1 python workbench/serve_local.py --port 8765`。`--port` 預設 8765，可給 `0` 讓系統挑空埠。**沒有** `--host` 或任何改綁定位址的參數、環境變數或設定。
- 綁定成功後 stdout 第一行印 `LISTENING 127.0.0.1 <實際埠號>`，之後持續服務直到被中止。
- `serve_local.py` 以 `from stop_policy import decide` 匯入 010 的函式（直接執行時 `workbench/` 本來就在 `sys.path[0]`；閘門以 `PYTHONPATH=workbench` 匯入）。本檔**不得**定義自己的 `decide`，也不得複製 010 的判斷規則。
- 匯入 `serve_local` 時不得綁埠、不得有輸出；只有 `main()`（`if __name__ == "__main__":` 底下）才啟動伺服器。

### R2 狀態名與「忙」

`serve_local.py` 模組頂層提供：

- `STATE_LABELS`：dict，鍵剛好是 009 §2.1 的 15 個狀態碼，值是該表的中文顯示（`REGISTERED`→`已登記`、`QUEUED`→`排隊中`、`STARTING`→`準備中`、`RUNNING`→`執行中`、`SAVING`→`保存中`、`COLLECTING`→`收產出中`、`RELEASING`→`釋放中`、`RELEASE_UNCONFIRMED`→`釋放未確認`、`PAUSED`→`已暫停`、`RECONCILING`→`核對中`、`UNKNOWN`→`狀態不明`、`BLOCKED`→`需要你處理`、`DONE`→`完成`、`FAILED`→`失敗`、`CANCELLED`→`已取消`）。
- `BUSY_STATES`：frozenset，剛好是 009 §2.1「算不算忙」為「是」（含「一律當忙」）的 9 個狀態：`STARTING`、`RUNNING`、`SAVING`、`COLLECTING`、`RELEASING`、`RELEASE_UNCONFIRMED`、`RECONCILING`、`UNKNOWN`、`BLOCKED`。
- `state_view(code)`：回傳 dict，鍵剛好 `code`、`label`、`busy`、`terminal`。`code` 原樣回傳；在 15 碼內時 `label` 取 `STATE_LABELS`、`busy` 依 `BUSY_STATES`、`terminal` 只有 `DONE`／`FAILED`／`CANCELLED` 為 true。**不在 15 碼內（含 None、空字串、大小寫不同）時：`label="狀態不明"`、`busy=true`、`terminal=false`**（009 §2.5：狀態不明一律當忙）。

### R3 假資料 `workbench/ui/fixtures/jobs.json`

- UTF-8，不得有重複鍵。頂層鍵剛好 `schema`、`notice`、`host`、`jobs`：`schema` 為 1；`notice` 為 `示意數字，非真實額度`；`host` 為 `online`。
- `jobs` 是清單，**至少 15 筆**，每筆鍵剛好 `now`、`snapshot`、`contract`、`policy`、`display`。
  - `now`、`snapshot`、`contract`、`policy` 的巢狀鍵集合與 `workbench/fixtures/scenarios.json` 的 `base` **完全相同**（不多不少）；值可以不同，但每筆都必須讓 `decide(snapshot, contract, policy, now)` 正常回傳、不 raise。
  - `snapshot.host` 一律等於頂層 `host`。
  - `contract.job_id` 唯一，格式 `demo-<J1|J3|WAN>-<三位數>`，且 `<類型>` 等於 `contract.job_type`。
  - `contract.cu_cap` 一律為 `10`（假資料）；`contract.submitted_by` 是 `human` 或 `bot:demo`。
  - `display` 鍵剛好 `title`（中文非空字串）、`progress_total`（正整數）、`cu_balance`（一律 `100`）、`cu_rate_per_hour`（0～10 的數字）、`note`（字串，可空；`BLOCKED` 的工作要寫一句白話原因，例如「第 23 批雜湊不符，已重試 3 次」）、`files`、`timeline`。
  - `files` 每項鍵剛好 `name`（只含英數、底線、點、連字號）、`size_bytes`（非負整數）、`sha256_8`（8 個小寫十六進位字元，假值）、`verify`（`verified`／`unverified`／`mismatch`）、`landed`（bool）。
  - `timeline` 每項鍵剛好 `at`（假時間軸分鐘數）、`from`（狀態碼或 null）、`to`（狀態碼）、`by`（`H`／`B`／`S`）。
- 涵蓋條件（閘門逐條驗）：
  1. 全部 `snapshot.state` 的集合包含 15 個狀態碼。
  2. `job_type` 三種都出現。
  3. 至少一筆 `RUNNING`、`human_hold=false`、`human_command="none"`、`bot_request="none"`、`probe.status="ok"`。
  4. 至少一筆 `human_hold=true` 且 `submitted_by="bot:demo"`。
  5. 至少一筆 `RELEASE_UNCONFIRMED`，且其 `release_check` 是 `active_nonzero` 或 `check_failed`。
  6. 至少一筆 `files` 裡有 `verify="mismatch"`。
- 檔內不得有網址、電子郵件、絕對路徑或 token 樣式字串。

### R4 API（`serve_local.handle`）

`serve_local.py` 模組頂層提供：

- `load_state()`：讀 `jobs.json`（路徑由本檔位置推出：同目錄的 `ui/fixtures/jobs.json`），回傳一個新的記憶體狀態物件（形狀自訂）。只讀檔，不寫檔。
- `handle(state, method, path, body)`：純分派函式，回傳 `(status, payload)`，`status` 是 int，`payload` 是可 JSON 化的 dict。`method` 是 `"GET"`／`"POST"` 等字串；`path` 是含 query 的路徑字串；`body` 是已解析的 dict 或 None。HTTP 層只負責解析與序列化，**所有行為都在 `handle`**，閘門會直接呼叫它，不必開埠。
- 錯誤 payload 鍵剛好 `reason_code`、`ui_message`（中文非空），不得含例外類別名、`Traceback`、檔案路徑或原始例外字串。

| 方法與路徑 | 行為 | 成功 |
|---|---|---|
| `GET /`、`GET /index.html`、`GET /app.js`、`GET /style.css` | 回 `workbench/ui/` 下對應檔（HTTP 層處理；`handle` 對這四條回 `200` 與 `{"static": "<檔名>"}`） | 200 |
| `GET /api/jobs` | 總覽：鍵剛好 `notice`、`host`、`host_label`、`wind_down`、`jobs`（每筆為「工作摘要」） | 200 |
| `GET /api/jobs/<job_id>` | 工作詳情：工作摘要的全部鍵，再加 `checkpoint`、`files`、`timeline`、`contract_summary`、`audit` | 200 |
| `POST /api/jobs/<job_id>/command` | 人工指令，body `{"command": ..., "confirm": bool}`（R5） | 200 |
| `POST /api/jobs/<job_id>/tick` | 系統推進一步（模擬）：用目前快照呼叫 `decide` 並套用（R5） | 200 |
| `POST /api/host` | body `{"host": "online"／"shutting_down"／"just_booted"}`；改頂層與每筆 `snapshot.host`，只重算決策，不套用轉移 | 200 |
| `POST /api/reset` | 重新 `load_state()`，丟掉記憶體裡的變更與稽核 | 200 |
| `POST /api/bot` | Bot 端口（R6） | 200 |
| 其他路徑 | `NOT_FOUND`（含 `/../`、`/fixtures/jobs.json`、`/serve_local.py`、`/stop_policy.py` 等） | 404 |
| `GET`／`POST` 以外的方法 | `METHOD_NOT_ALLOWED` | 405 |

不存在的 `job_id` 一律 404 `NOT_FOUND`。body 不是 JSON 物件時 400 `BAD_JSON`（HTTP 層判；`handle` 收到非 dict 的 body 也回 400 `BAD_JSON`）。

**工作摘要**鍵剛好：

| 鍵 | 內容 |
|---|---|
| `job_id`、`title`、`job_type` | 來自假資料 |
| `state`、`state_label`、`busy`、`terminal` | `state_view(snapshot.state)` |
| `submitted_by` | 原值；`submitter_label` 是 `人`（`human`）或 `Bot`（`bot:` 開頭） |
| `submitter_label` | 見上 |
| `human_hold` | bool |
| `progress` | `{"value": snapshot.progress.value, "total": display.progress_total}` |
| `cu` | `{"used", "soft", "cap", "balance", "rate_per_hour", "minutes_to_cap", "notice"}`；`soft = cu_soft_ratio × cu_cap`；`minutes_to_cap` 為 `(cap - used) / rate × 60`（rate 為 0 或已超過上限時為 null）；`notice` 等於頂層 `notice` |
| `release_label` | `state == RELEASE_UNCONFIRMED` → `釋放未確認`；`state == RELEASING` → `釋放中`；否則 `release_check == confirmed_zero` → `已確認 0 active`；其他 → `無釋放回查` |
| `decision` | 目前快照的 `decide` 回傳值（9 鍵原樣）；`decide` raise `ValueError` 時為 null |
| `decision_error` | 正常為 null；`decide` raise `ValueError` 時為 `INPUT_INVALID`，此時 `busy=true` |
| `blocker` | `state` 是 `BLOCKED`／`RELEASE_UNCONFIRMED`／`UNKNOWN`，或 `decision.notify_human` 為 true 時：`{"message": ..., "suggested": ["tick", "stop_after_save", "stop_now"]}`，`message` 取 `display.note`（非空時），否則取 `decision.ui_message`（`decide` 失敗時為「狀態不明，請先核對」）；否則 null |

`host_label`：`online`→`在線`、`shutting_down`→`即將關機`、`just_booted`→`剛開機核對中`。`wind_down`：關機前需先收尾的 `job_id` 清單，依 `jobs.json` 順序；條件是目前決策為 `REQUEST_SAVE`＋`HOST_SHUTDOWN`，或 `reason_code` 為 `HOST_OFFLINE_REMOTE_RUNNING`（`REGISTERED`／`QUEUED` 的 `WAIT`＋`HOST_SHUTDOWN` 只是不啟動，不算）。`host` 為 `online` 時清單為空。

**「釋放未確認」不得顯示成完成**：`state == RELEASE_UNCONFIRMED` 的工作摘要裡，`state_label`、`release_label` 都是 `釋放未確認`，`busy=true`、`terminal=false`。顯示用的標籤欄位（`state_label`、`release_label`）不得含 `完成`、`已睡`、`睡眠`，`release_label` 也不得是 `已確認 0 active`。（`decision.ui_message` 由 010 產生，例如「釋放尚未確認，不能顯示為完成。」，不在此限。）

### R5 人工指令與套用規則

`POST /api/jobs/<job_id>/command`，`command` 必須是 `stop_after_save`／`stop_now`／`pause`／`resume`，否則 400 `BAD_PARAM`。

- `stop_now` 且 `confirm` 不是 `true`：回 409 `CONFIRM_REQUIRED`，**不呼叫 `decide`、不改任何狀態**，只記一筆稽核。
- 其他情況：複製目前快照，設 `snapshot.human_command = command`，呼叫 `decide`，再依下列「套用」。

`tick` 與 Bot 的 `request_pause` 也用同一個「套用」，只是設的欄位不同（`tick` 什麼都不設；`request_pause` 設 `snapshot.bot_request = "pause"`）。

**套用**（唯一的轉移方式；不得在 `decide` 之外改 `state`）：

1. `decide` raise `ValueError` → 回 422 `INPUT_INVALID`，狀態不變。
2. `action == REJECT_REQUEST` → 狀態不變。
3. 其他 → `snapshot.state = next_state`、`snapshot.human_hold = human_hold_after`、`snapshot.stop_intent = stop_intent`。
4. 不論結果，`snapshot.human_command` 與 `snapshot.bot_request` 都回到 `none`；其他欄位不動。
5. 成功回應鍵剛好 `job_id`、`accepted`（`action != REJECT_REQUEST`）、`decision`（9 鍵原樣）、`job`（套用後的工作摘要）。

人工鎖因此完全由 010 決定：人下 `stop_after_save`／`stop_now`／`pause` 後 `human_hold_after=true`，之後 Bot 的請求被 `decide` 以 `HUMAN_HOLD` 拒絕；只有人下 `resume`（`PAUSED` 時）才解鎖。

### R6 Bot 端口（`POST /api/bot`）

body 鍵：`action`（必填）、`caller`（必填，`bot:` 開頭）、`job_id`、`state`（視動作）。

- body 有任何鍵名（不分大小寫）含 `token`、`auth`、`password`、`secret`、`cookie`、`api_key`、`apikey`、`session` → 400 `CREDENTIAL_REFUSED`；回應與稽核都**不得**含該值。
- `caller` 缺或不是 `bot:` 開頭 → 400 `BAD_CALLER`。
- `action` 只接受下列四個；其他任何值（例如 `resume`、`stop_now`、`release`、`unlock`、`set_cap`、`read_file`、`exec`）→ 403 `ACTION_NOT_ALLOWED`，狀態不變。

| `action` | 本單行為 | 回應鍵（剛好） |
|---|---|---|
| `list_jobs` | 可選 `state` 篩選（必須是 15 碼之一，否則 400 `BAD_PARAM`） | `ok`（true）、`jobs`（每筆鍵剛好 `job_id`、`state`、`state_label`、`progress`、`reason_code`） |
| `get_status` | 依 `job_id` | `ok`、`job_id`、`state`、`state_label`、`progress`、`reason_code`、`ui_message` |
| `request_pause` | 設 `bot_request="pause"` 後走 R5「套用」 | `ok`、`job_id`、`accepted`、`reason_code` |
| `submit_job` | **不做**：不新增任何工作 | `ok`（true）、`accepted`（false）、`reason_code`（`NOT_IN_PROTOTYPE`） |

`reason_code`、`ui_message` 取目前決策；`decide` 失敗時 `reason_code` 為 `INPUT_INVALID`。Bot 回應不含 `timeline`、`audit`、`files`、`contract_summary` 或任何原始日誌。

### R7 稽核（只在記憶體）

- 每次 `POST`（含被拒、409、400、403）在狀態物件的稽核清單尾端加一筆，鍵剛好 `at`（該工作的假 `now`，無工作時用 null）、`caller`（`human` 或 Bot 的 `caller`）、`action`、`job_id`（或 null）、`result`（回應的 `reason_code`，成功時為決策的 `reason_code`；`reset` 為 `RESET`）。
- 稽核只加不改；`reset` 後清空。詳情 API 的 `audit` 回該 `job_id` 的稽核，依加入順序。
- 不寫檔、不印到 stdout（`LISTENING` 那行除外）。

### R8 伺服器與網路界線

- 綁定位址寫死成字串常數 `HOST = "127.0.0.1"`，伺服器物件以 `(HOST, port)` 建立；除了 `HOST` 的 `127.0.0.1`，檔內不得有其他位址字串常值（特別是 `0.0.0.0`、`localhost`、`::`），也不得以空字串綁定。
- 允許的 import 只有 `argparse`、`copy`、`http.server`、`json`、`pathlib`、`socketserver`、`sys`、`urllib.parse`、`stop_policy`；其他一律不准（特別是 `os`、`socket`、`ssl`、`subprocess`、`urllib.request`、`http.client`、`threading`、`time`、`datetime`、`tempfile`、`shutil`、`logging`、`importlib`）。需要多執行緒時用 `http.server.ThreadingHTTPServer`，不另 import。
- 不呼叫 `open`、`eval`、`exec`、`compile`、`__import__`；不呼叫 `write_text`、`write_bytes`、`mkdir`、`unlink`、`rename`、`touch`；讀檔只用 `Path.read_bytes`／`Path.read_text`，且只讀 `ui/` 下四個靜態檔與 `jobs.json`。
- 不讀任何 HTTP 標頭的 `Authorization`／`Cookie`，不設 cookie。
- 回應一律帶 `Cache-Control: no-store`；靜態檔與 API 都只走同源。

### R9 前端（`index.html`、`app.js`、`style.css`）

- `index.html`：`<html lang="zh-Hant">`；只引用 `<script src="app.js">` 與 `<link rel="stylesheet" href="style.css">`，沒有其他 `src`／`href`（錨點 `#...` 除外）。
- 下列 9 個區塊各是一個帶 `id` 的元素，且該元素內的文字含右欄的中文標籤（009 §5）：

| `id` | 中文標籤 |
|---|---|
| `section-job-list` | 任務列表 |
| `section-job-detail` | 任務詳情 |
| `section-blocker` | 阻塞原因 |
| `section-cu` | CU 面板 |
| `section-outputs` | 產出與雜湊 |
| `section-release` | 釋放狀態 |
| `section-stop` | 停止 |
| `section-host` | 本機狀態 |
| `section-onboarding` | 首次引導 |

- `section-cu` 內有固定文字 `示意數字，非真實額度`。
- `section-stop` 內剛好兩個 `<button>`：`id="btn-stop-after-save"` 文字 `保存後停止（建議）`；`id="btn-stop-now"` 文字 `立即停止（可能遺失未保存產出）`。
- `section-onboarding` 內有一個 `<ol>`，剛好 3 個 `<li>`，依序含 `看列表`、`看阻塞原因`、`怎麼停`。
- 每個 `<button>` 的文字至少有一個中日韓文字。
- `app.js`：
  - 所有 `fetch(` 的第一個參數都以字串常值 `/api/` 開頭（`'`、`"` 或反引號皆可）；不得出現 `XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`import(`、`eval(`、`new Function`、`document.cookie`、`localStorage`、`sessionStorage`。
  - 不得用 `innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`；文字一律用 `textContent`（假資料也一樣）。
  - 立即停止：先 `window.confirm(...)`，提示文字含 `可能遺失未保存產出`；使用者按確定才送 `{"command": "stop_now", "confirm": true}`。
  - **不得含任何 15 個狀態碼或 010 R3 的 11 個動作碼的大寫字樣**（以整字比對，例如 `RUNNING`、`RELEASE_UNCONFIRMED`、`REQUEST_SAVE`）。狀態中文名、忙／閒、釋放標籤都用 API 回的欄位；樣式用 `"state-" + job.state` 之類組出 class，不在前端寫狀態判斷。
- `style.css`：不得含 `@import`、`url(`；要有 `.state-RELEASE_UNCONFIRMED` 規則（警示色），且不得與 `.state-DONE` 共用同一條規則。
- 三個前端檔都不得含 `http://`、`https://`、`//` 開頭的協定相對網址、電子郵件、絕對路徑或 token 樣式字串。
- 本檔所說的「絕對路徑」指**檔案系統**路徑（例如 `/home/`、`/Users/`、`/tmp/`、`/etc/` 開頭，或 `C:\` 這類磁碟機代號）；`/api/...` 路由與 `/`、`/index.html` 這類同源網址路徑不算。R3、R8、R9 的衛生規則都照這個定義。

## Definition of done（全部可機器判定）

1. `python tools/check_011.py` exit 0，最後一行 `RESULT: ALL PASS`。
2. 實作 PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠：選到 `011`、`scope: PASS`、`lock: PASS`、`CI RESULT: PASS`。
3. 實作 PR diff（相對 main，三點 diff）的檔案集合 == {`workbench/serve_local.py`, `workbench/ui/index.html`, `workbench/ui/app.js`, `workbench/ui/style.css`, `workbench/ui/fixtures/jobs.json`}。
4. `python tools/check_010.py` 在同一棵樹上仍 exit 0（010 三檔未被改動）。
5. 擁有者在自己電腦上開一次原型給意見：可選，不阻擋合併。

## 閘門（給 Gpt小豬，本 PR 不寫）

`tools/check_011.py` 沿用 007、008、010 的寫法：標準庫、離線、ASCII stdout；子程序設 `PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`、自設 `PYTHONPATH=workbench`；活檔只讀，突變在暫存複本；每項印 `[PASS]`／`[FAIL]`／`[BLOCKED]`，結尾 `RESULT: ALL PASS` 或 `RESULT: FAIL`。建議 G1～G10 另附在閘門 PR 的交接說明；最低要求是 R1～R9 每條至少有一項機器檢查，並含「把 `stop_policy.decide` 換成哨兵包裝後，`serve_local` 的回應跟著變」的突變檢查，證明轉移真的走 010。

## 範圍與 PR 形狀（CI 會怎麼判）

`tools/ci_run_gates.py` 用**整張 PR 的 diff** 判範圍。

- **PR A（本 PR，spec only）**：只新增 `specs/011-workbench-mock-ui.md`。spec 沒有 `expected_paths` 表格列 → `discover()` 略過本檔；diff 不碰任何工單的 `expected_paths` → regression 模式跑 001～008 與 010 全部閘門，應與 main 同為綠。lock 不動。
- **PR B（閘門＋鎖，Gpt小豬）**：把 expected_paths 移進表格、加 `tools/check_011.py`、lock 加 011（三者同一張 PR）。預期選到 011、scope／lock PASS、`check_011` 紅（尚未實作），回歸項（`check_010`）綠。
- **PR C（實作，Gemi小狗，PR B 合進 main 後才開）**：只新增五個檔（`workbench/serve_local.py` 與 `workbench/ui/` 下四檔）。只 `git add` 這五檔並設 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 進 diff 造成 `scope: FAIL`。證據貼 PR 留言，不進 diff。

## 不做的事

- 不改 `src/`、`tests/`、`fixtures/`、`.github/`、`specs/001`～`010`。
- 不改 010 的三個 `workbench/` 檔；不改 `tools/check_001.py`～`check_010.py`、`tools/ci_run_gates.py`，不改 lock 裡既有紀錄。
- 不接真遠端、不連外部網路、不放憑證、不做端口授權（切片 ④ 與 009 §6.3 待決）。
- 不加 pytest 或任何 pip 依賴；伺服器不寫檔。
- 不把 `gate` 設成 required（repo 設定由擁有者決定）。
