# Work order 009 - 本地工作台規格（切片 ①，只有規格）

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-11-09 JST）。本 PR **只含這份 spec**；沒有實作、閘門或鎖。切片 ②、③ 各自後續開單 |
| Repo | https://github.com/Kyo14363/hello （工作台程式放獨立子目錄 `workbench/`） |
| Upstream | 無。與 001～008 互不相依，不 import `src/` 裡任何模組 |
| Implementer | spec **Clau小羊**；驗收與合併 **Gro小貓**。切片 ②、③ 的閘門 **Gpt小豬**、實作 **Gemi小狗**（Cursor 雲端 agent） |
| Definition of done | 見下方「Definition of done（切片 ①）」 |

> ⚠ 本檔刻意**不放** `expected_paths` 表格列，也沒有 `tools/check_009.py`。`tools/ci_run_gates.py` 會把沒有該列的 spec 當成「還不是工單」略過。切片 ① 的產物只有這份文件，所以 009 不設閘門；切片 ②、③ 另開 010、011（編號開單時確認），各自帶 spec、閘門與鎖。

## 用途

吸收開源專案 Wakeloom 可借用的設計，在本機做「人用起來順手的本地介面」，加上「讓 Bot 維持日常任務的受控端口」。人與 Bot 操作同一批工作、同一個狀態機。

已定前提（2026-11-07）：**本機關機就暫停，開機後再接續；不設雲端常駐協調。**

本檔是公開版：不含私人路徑、帳號、真實額度數字或憑證。測試與原型裡出現的 CU（運算單位）數字一律是**假資料**，不代表真實額度。

---

## 1. 目標與不做什麼

### 1.1 目標
1. 一個中文、低認知負擔的本地介面：一眼看懂「哪個工作在跑、走到哪、花了多少、卡在哪、產出有沒有保住、資源有沒有真的釋放」。
2. 一個只接受登記動作的 Bot 端口，讓 Bot 例行可以查狀態、提交登記好的工作、請求暫停，而不能下任意指令。
3. 一個人與 Bot 共用的 job 狀態機，加一個可離線測試的停機決策純函式。
4. 把我們實際吃過的虧寫成規則：斷線導致未下載產出遺失、程式下載沒落地、畫面顯示已睡但未確認釋放、套件版本讀不了舊 checkpoint。

### 1.2 第一期不做（硬界線）
| 不做 | 原因 |
|---|---|
| 不接真 Colab（不開執行階段、不扣運算單位） | 先用假資料驗證狀態機與介面；接真環境是切片 ④，另批 |
| 不放任何憑證（token、cookie、OAuth client、API key） | Wakeloom 的明文 refresh token 與未遮罩日誌是已知風險路徑 |
| 不呼叫任何非公開端點 | Wakeloom 本機模式依賴非公開介面，作者自己標為實驗性、可能有帳號風險 |
| 不碰現行訓練與現行 Colab 例行 | 現行工作照原流程由瀏覽器操作，不受本專案影響 |
| 不花錢（不買、不升級、不開付費服務） | 硬性準則 |
| 不做雲端常駐協調者 | 已定：本機關機即暫停 |
| 不做 ComfyUI-only 的閒置判斷 | 佇列空不等於訓練完成或產出已保存 |
| 不開放 Bot 任意指令、任意檔案存取 | 端口只做登記動作 |

### 1.3 從 Wakeloom 借什麼、不借什麼
| 借（概念） | 不借 |
|---|---|
| 停機決策是純規則函式，與狀態快照分開，可離線測 | `queue_busy` 只看 ComfyUI，查詢失敗回「不忙」 |
| watchdog 獨立程序、失聯時多次確認 | 最長會話／預算硬限制直接跳過忙碌保護 |
| 備份不被預設值覆蓋 | 備份失敗只警告仍停機；釋放失敗畫面仍顯示睡眠 |
| CU 面板、佇列、取消／重試、斷線續跑、產出自動拉回、中文參數面板、首次引導 | 明文保存 refresh token；原始錯誤字串直接進日誌 |
| PKCE（切片 ④若需 OAuth 才考慮） | 把非公開端點當穩定契約 |

---

## 2. 單一 job 狀態機（人與 Bot 共用）

### 2.1 狀態
| 代碼 | 中文顯示 | 意義 | 算不算「忙」 |
|---|---|---|---|
| `REGISTERED` | 已登記 | 合約已驗證，尚未排入 | 否 |
| `QUEUED` | 排隊中 | 等待啟動條件（本機在線、無其他獨占工作、預算足夠） | 否 |
| `STARTING` | 準備中 | 取得運算資源、安裝、載入 | 是 |
| `RUNNING` | 執行中 | 心跳正常、進度前進 | 是 |
| `SAVING` | 保存中 | 已要求寫 checkpoint／收批次，等確認 | 是 |
| `COLLECTING` | 收產出中 | 下載產出並逐檔驗 sha256 | 是 |
| `RELEASING` | 釋放中 | 已送出釋放，等回查 | 是 |
| `RELEASE_UNCONFIRMED` | 釋放未確認 | 回查失敗或仍有 active 資源；**不得顯示為完成或已睡** | 是 |
| `PAUSED` | 已暫停 | 已保存到可續跑的點，資源已確認釋放 | 否 |
| `RECONCILING` | 核對中 | 開機後或狀態可疑時，核對進度、已保存產出與遠端狀態 | 是 |
| `UNKNOWN` | 狀態不明 | 查詢失敗、逾時或紀錄互相矛盾 | **一律當忙** |
| `BLOCKED` | 需要你處理 | 規則無法自行決定，等人 | 是（資源可能仍在） |
| `DONE` | 完成 | 產出已驗 sha256，且釋放後確認 0 active | 否 |
| `FAILED` | 失敗 | 已收掉，保存了能保存的，原因已記錄 | 否 |
| `CANCELLED` | 已取消 | 啟動前就取消，或人工確認放棄 | 否 |

終態：`DONE`、`FAILED`、`CANCELLED`。只有在「已確認 0 active」後才能進終態；若釋放沒確認，停在 `RELEASE_UNCONFIRMED`。

### 2.2 觸發者
- **人（H）**：透過本地介面。
- **Bot（B）**：只能透過第 6 節端口的登記動作。
- **系統（S）**：本地協調程序與 watchdog，依第 4 節決策函式行動。

### 2.3 轉移表
| 從 | 到 | 條件 | 可觸發者 |
|---|---|---|---|
| （無） | `REGISTERED` | 合約通過驗證，類型在允許清單 | H、B |
| `REGISTERED` | `QUEUED` | 排入 | H、B |
| `REGISTERED`／`QUEUED` | `CANCELLED` | 取消（尚未取得資源） | H；B 只能取消自己提交且未啟動的 job |
| `QUEUED` | `STARTING` | 本機在線、非關機中、無獨占衝突、預算餘裕足夠 | S |
| `STARTING` | `RUNNING` | 第一個有效心跳（step／批次已前進） | S |
| `STARTING` | `FAILED` | 準備逾時或安裝失敗；先走釋放與回查 | S |
| `RUNNING` | `SAVING` | 決策函式要求保存（預算軟上限、時間將到、人工／Bot 請求暫停、本機即將關機） | S（由 H／B 請求引起） |
| `RUNNING` | `COLLECTING` | 工作自報完成，且最後 checkpoint／批次已確認 | S |
| `SAVING` | `COLLECTING` | checkpoint 已確認（寫入完成並回讀確認） | S |
| `SAVING` | `BLOCKED` | 保存逾時，且觸及硬上限（見 4.4 衝突規則） | S |
| `COLLECTING` | `RELEASING` | 本階段應收產出全部下載並驗 sha256 相符 | S |
| `COLLECTING` | `BLOCKED` | sha256 不符或下載未落地，重試次數用完 | S |
| `RELEASING` | `PAUSED` | 確認 0 active，且來源是暫停請求 | S |
| `RELEASING` | `DONE` | 確認 0 active，且工作已完成 | S |
| `RELEASING` | `FAILED` | 確認 0 active，且來源是失敗或停滯 | S |
| `RELEASING` | `RELEASE_UNCONFIRMED` | 回查失敗或 active ≠ 0 | S |
| `RELEASE_UNCONFIRMED` | `RELEASING` | 重試釋放 | S、H |
| `PAUSED` | `QUEUED` | 續跑（從最後確認的 checkpoint） | H；B 只能對**沒有人工鎖**的 job 請求續跑 |
| 任何非終態 | `UNKNOWN` | 查詢失敗、逾時、紀錄矛盾 | S |
| `UNKNOWN` | `RECONCILING` | 自動重查或人工要求核對 | S、H |
| `RECONCILING` | 原狀態或 `PAUSED`／`COLLECTING`／`BLOCKED` | 依核對結果（見 2.6） | S |
| 任何非終態 | `SAVING` | **人工「保存後停止」** | H |
| 任何非終態 | `RELEASING` | **人工「立即停止」**（介面二次確認，明示可能遺失未保存產出；紀錄寫入稽核） | H |
| `BLOCKED` | 人選的下一步 | 人選擇：重試、保存後停、立即停、放棄 | H |

### 2.4 人工優先規則
1. 人工停止／暫停一旦發出，job 加上**人工鎖**（`human_hold=true`，記錄時間 JST 與動作）。
2. 有人工鎖的 job，Bot 的提交、續跑、暫停請求一律拒絕，回應理由碼 `HUMAN_HOLD`；只有人能解鎖。
3. 人可以搶停 Bot 提交的 job；Bot 不能搶停人提交的 job，只能「請求暫停」，而且請求只會走「保存後暫停」路徑，不會立即停。
4. 同一時間人與 Bot 的請求衝突，以人為準；稽核紀錄同時保存兩邊請求。

### 2.5 狀態不明一律當忙
- 任何查詢失敗、逾時、解析錯誤都**不能**被解讀成「閒置」或「已完成」。
- `UNKNOWN` 期間：不釋放（除非人工立即停止）、不啟動新工作、不顯示為睡眠或完成。
- 連續確認：失聯需達 `probe_confirm_count` 次（預設 3 次、間隔 `probe_interval`）才轉 `UNKNOWN`；單次失敗只記錄。
- `UNKNOWN` 超過 `unknown_alert_minutes` 轉 `BLOCKED` 通知人。預算硬上限在 `UNKNOWN` 期間的處理見 4.4（待擁有者決定）。

### 2.6 本機關機與開機
已定原則：本機是唯一協調者，關機即暫停；開機後先核對、再接續。

**關機時（可預期的正常關機）**
1. 立即停止啟動新工作（`QUEUED` 不再轉 `STARTING`）。
2. 只在本機本機跑的步驟：轉 `SAVING` → `PAUSED`。
3. **遠端已在跑的工作不會因本機關機而停**，必須依合約欄位 `on_host_offline` 處理：
   - `pause_safely`（建議預設）：關機前先要求保存並收已完成的產出，確認釋放後才轉 `PAUSED`；介面提醒「還有 N 個遠端工作需要先收尾，預估 X 分鐘」，讓人選「等收尾再關機」或「仍要關機」。
   - 人選「仍要關機」：job 標記 `host_offline_while_remote_running=true`，開機後一定走 `RECONCILING`；介面明講「遠端可能仍在計費」。
4. 切片 ④之前沒有真遠端，此規則只在模擬中測試。接真環境前，必須另訂「遠端端自己的安全暫停」：遠端要有自己的時間與預算上限守衛，不依賴本機在線（見第 7 節 ④ 第 3 點）。

**非預期關機（斷電、當機、睡眠）**
- 沒有收尾機會。開機後所有非終態 job 一律視為 `UNKNOWN` → `RECONCILING`。

**開機後核對順序（RECONCILING）**
1. 讀本機工作日誌（append-only），找出每個 job 最後一個已確認的事件。
2. 核對已保存產出：逐檔重算 sha256，與清單比對；不符或缺檔的標「未保存」。
3. 核對最後確認的 checkpoint（step、時間、位置、驗證結果）。
4. 查遠端狀態（切片 ④才有）；查不到 → 維持 `UNKNOWN`，不重啟、不釋放，通知人。
5. 決定去向：
   - 遠端仍在跑且心跳前進 → 回 `RUNNING`。
   - 遠端已結束、產出在遠端未下載 → `COLLECTING`。
   - 遠端已釋放、有可用 checkpoint → `PAUSED`，等人或 Bot（無人工鎖時）續跑。
   - 已完成的批次或步驟**不重跑**；續跑只從最後確認的 checkpoint 或第一個未驗證批次開始。
   - 紀錄矛盾 → `BLOCKED`。
6. 核對結束前，不啟動任何新工作。

---

## 3. 工作合約欄位

每個 job 提交時必須帶完整合約；缺欄位或超出範本上下限就拒絕登記。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `job_id` | 字串 | 唯一；格式建議 `YYYYMMDD-類型-序號`（日期以 JST） |
| `template_id` | 字串 | 必須在登記範本清單內；Bot 只能用範本 |
| `job_type` | 列舉 | `J1`（批次影格推論）、`J3`（LLM LoRA 訓練）、`WAN`（影片推論）；其他類型第一期不收 |
| `workload_kind` | 列舉 | `training` 或 `batch_inference`；決定「忙」與「完成」的判斷方式 |
| `gpu` | 列舉 | 範本允許的 GPU 種類；不允許時拒絕而非自動降級 |
| `gpu_fallback` | 列舉或空 | 明列可接受的替代，未列就不替代 |
| `cu_cap` | 數字 | 此 job 運算單位硬上限 |
| `cu_soft_ratio` | 數字 | 軟上限比例（預設 0.8），到達即要求保存 |
| `save_grace_cu`／`save_grace_minutes` | 數字 | 硬上限時為保存產出允許的寬限（待擁有者決定，見 4.4） |
| `max_minutes` | 整數 | 最長執行時間 |
| `heartbeat` | 物件 | `unit`（`step` 或 `batch`）、`expected_interval_s`、`stall_minutes`（預設 20，沿用現行做法） |
| `progress_total` | 整數 | 總 step 數或總批次數 |
| `checkpoint_policy` | 物件 | `every_n_steps`／`every_n_batches`、`confirm_method`（寫入後回讀＋大小／雜湊確認）、`keep_last_n` |
| `resume_from` | 字串或空 | 續跑時指定已確認的 checkpoint id |
| `outputs` | 清單 | 每項：邏輯名稱、預期類型、是否必要；完成時每檔都要有 sha256 |
| `download_verify` | 固定 `sha256` | 下載後逐檔比對；不符即重試，用完轉 `BLOCKED` |
| `release_confirm` | 物件 | 釋放後回查次數與間隔；必須讀到 **0 active** 才算釋放 |
| `on_host_offline` | 列舉 | `pause_safely`（預設）或 `continue_until_checkpoint` |
| `submitted_by` | 列舉 | `human` 或 `bot:<名稱>` |
| `human_hold` | 布林 | 人工鎖（系統維護，不可由 Bot 設或解） |
| `notes` | 字串 | 自由備註；不得含憑證或私人路徑 |

「忙」與「完成」的判斷依 `workload_kind`：
| 類型 | 忙 | 完成證據 | 可釋放條件 |
|---|---|---|---|
| `training`（J3） | 程序活著且 step 在前進 | checkpoint 寫入並回讀確認；最終產物 sha256 相符 | 最終產物已下載並驗 sha256 |
| `batch_inference`（J1／WAN） | 批次清單還有未處理或未下載的項目 | 每批下載並驗 sha256 | 全部批次已下載並驗過 |

心跳的定義是**進度前進**（step 或批次數增加），不是「程序還活著」或「網頁還連著」。

---

## 4. 停機決策純函式

### 4.1 介面
`decide(snapshot, contract, policy, now) -> Decision`
- 純函式：不讀檔、不連網、不讀時鐘（時間由 `now` 傳入）、不改輸入。
- 相同輸入必得相同輸出，可完全離線測試。
- 執行動作（保存、下載、釋放）由呼叫端依 `Decision` 進行，函式本身不做任何副作用。

### 4.2 輸入
| 名稱 | 內容 |
|---|---|
| `snapshot.state` | 目前狀態（第 2.1 節） |
| `snapshot.probe` | `ok`／`failed`／`timeout`、連續失敗次數、最後成功時間 |
| `snapshot.progress` | 目前 step／批次、上次前進時間 |
| `snapshot.checkpoint` | 最後確認的 step、確認時間、是否已確認 |
| `snapshot.outputs` | 已產生未下載數、已下載未驗數、驗證失敗數 |
| `snapshot.cu_used` | 本 job 已用運算單位（假資料） |
| `snapshot.elapsed_minutes` | 已執行分鐘 |
| `snapshot.human_command` | `none`／`stop_after_save`／`stop_now`／`pause`／`resume` |
| `snapshot.bot_request` | `none`／`pause`／`resume`／`submit` |
| `snapshot.human_hold` | 人工鎖 |
| `snapshot.host` | `online`／`shutting_down`／`just_booted` |
| `snapshot.release_check` | `not_started`／`confirmed_zero`／`active_nonzero`／`check_failed` |
| `snapshot.done_signal` | 工作是否自報完成 |
| `contract` | 第 3 節欄位 |
| `policy` | `probe_confirm_count`、`unknown_alert_minutes`、`budget_conflict_mode`（見 4.4） |

### 4.3 輸出
| 名稱 | 內容 |
|---|---|
| `action` | `CONTINUE`、`WAIT`、`REQUEST_SAVE`、`COLLECT`、`RELEASE`、`RECHECK_RELEASE`、`RECONCILE`、`MARK_UNKNOWN`、`ESCALATE`（轉 `BLOCKED`）、`REJECT_REQUEST` |
| `next_state` | 建議的下一狀態 |
| `reason_code` | 例如 `HUMAN_STOP`、`HUMAN_HOLD`、`PROBE_UNCERTAIN`、`STALLED`、`CU_SOFT_CAP`、`CU_HARD_CAP_UNSAVED`、`MAX_TIME`、`HOST_SHUTDOWN`、`BOOT_RECONCILE`、`SHA_MISMATCH`、`RELEASE_NOT_CONFIRMED`、`COMPLETE` |
| `ui_message` | 中文一句話，給人看的阻塞原因或下一步 |
| `data_at_risk` | 布林；這個動作是否可能讓未保存產出遺失 |

### 4.4 判斷順序（先符合者先決定）
1. **人工指令**：`stop_now` → `RELEASE`（`data_at_risk` 依實際狀況標）；`stop_after_save`／`pause` → `REQUEST_SAVE`。
2. **Bot 請求遇人工鎖** → `REJECT_REQUEST`（`HUMAN_HOLD`）。
3. **本機狀態**：`just_booted` → `RECONCILE`；`shutting_down` → 依 `on_host_offline` 走 `REQUEST_SAVE`。
4. **查詢不確定**：失敗未達確認次數 → `WAIT`；達到 → `MARK_UNKNOWN`；`UNKNOWN` 超時 → `ESCALATE`。**任何查詢失敗都不得導出 `RELEASE` 或 `DONE`。**
5. **釋放回查**：`active_nonzero`／`check_failed` → `RECHECK_RELEASE`，次數用完 → `ESCALATE`，狀態停在 `RELEASE_UNCONFIRMED`。
6. **下載驗證**：sha256 不符 → 重新下載；次數用完 → `ESCALATE`。
7. **預算與時間**：
   - 到 `cu_soft_ratio × cu_cap` 或 `max_minutes` 前的保存點 → `REQUEST_SAVE`。
   - 到硬上限且產出都已保存 → `COLLECT`／`RELEASE`。
   - **到硬上限但有未保存產出 → 衝突，依 `budget_conflict_mode`。【待擁有者決定】**
8. **停滯**：查詢正常、程序活著但進度超過 `stall_minutes` 沒前進 → 收已保存的產出後釋放（沿用現行做法「卡住超過 20 分鐘沒進度就收掉」）；未保存部分在 `ui_message` 明列。
9. **完成**：`done_signal` 且最後保存已確認 → `COLLECT` → 驗完 → `RELEASE`。
10. 其他 → `CONTINUE`。

**預算硬停與保進度衝突（待擁有者決定）**，`budget_conflict_mode` 三個選項：
| 選項 | 行為 | 優點 | 缺點 |
|---|---|---|---|
| A. 硬停優先 | 到上限立即釋放，接受遺失 | 花費絕不超過上限 | 可能丟掉整段進度（過去曾因斷線遺失多組產出） |
| B. 保進度優先 | 等保存完成才停，不設上限 | 不丟產出 | 保存卡住時花費無上限 |
| **C. 有限寬限（建議預設）** | 到上限先要求保存，最多再用 `save_grace_cu` 或 `save_grace_minutes`（兩者先到者）；寬限用完仍未保存就停，標 `data_at_risk=true` 並通知 | 上限明確且可預期，大多數情況保得住 | 最壞多花一小段寬限 |

建議預設：C，寬限取「該 job `cu_cap` 的 10%」與「15 分鐘」先到者，並在軟上限（80%）就提前要求保存，讓多數情況根本不會撞到硬上限。**查詢不明（UNKNOWN）時撞到硬上限**：建議同樣只給寬限，寬限後轉 `BLOCKED` 立刻通知人，不自動判空閒；是否允許自動停，同列待決。

### 4.5 離線測試情境（至少 12 條，由工單 010（切片 ②）實作為單元測試）
以下數字皆為假資料。

| # | 情境 | 關鍵輸入 | 預期輸出 |
|---|---|---|---|
| T01 | 查詢單次失敗 | `RUNNING`，probe=failed，連續 1 次（確認門檻 3） | `WAIT`；不釋放 |
| T02 | 查詢連續失敗達門檻 | probe=timeout，連續 3 次 | `MARK_UNKNOWN`；next=`UNKNOWN`；不得為 `RELEASE` |
| T03 | 狀態不明過久 | `UNKNOWN` 超過 `unknown_alert_minutes` | `ESCALATE`；next=`BLOCKED`；`ui_message` 說明需要人處理 |
| T04 | 心跳停滯 | probe=ok、程序活著、step 25 分鐘沒前進（門檻 20） | `COLLECT`（收已保存）→ 後續 `RELEASE`；reason=`STALLED` |
| T05 | 程序活著不等於前進 | probe=ok、程序活著、step 剛前進 | `CONTINUE` |
| T06 | 預算軟上限 | cu_used=8，cu_cap=10，ratio=0.8 | `REQUEST_SAVE`；reason=`CU_SOFT_CAP` |
| T07 | 硬上限＋產出已保存 | cu_used=10，cap=10，未保存=0 | `COLLECT`／`RELEASE`；`data_at_risk=false` |
| T08 | 硬上限＋未保存（模式 C，寬限內） | cu_used=10.5，cap=10，grace=1，未保存 2 批 | `REQUEST_SAVE`；reason=`CU_HARD_CAP_UNSAVED` |
| T09 | 硬上限＋未保存（模式 C，寬限用完） | cu_used=11.1，cap=10，grace=1，未保存 2 批 | `RELEASE`；`data_at_risk=true`；通知人 |
| T10 | 同 T08 但模式 A／B | 模式 A；模式 B | A：`RELEASE` 且 `data_at_risk=true`；B：`REQUEST_SAVE` 持續等待 |
| T11 | 使用者搶停 Bot 工作 | submitted_by=bot，human_command=`stop_after_save` | `REQUEST_SAVE`；設人工鎖 |
| T12 | Bot 想續跑有人工鎖的 job | `PAUSED`，human_hold=true，bot_request=`resume` | `REJECT_REQUEST`；reason=`HUMAN_HOLD` |
| T13 | 人工立即停止 | human_command=`stop_now`，未保存 1 批 | `RELEASE`；`data_at_risk=true`；稽核紀錄 |
| T14 | 本機正常關機、遠端在跑 | host=`shutting_down`，on_host_offline=`pause_safely` | `REQUEST_SAVE`；完成後 next=`PAUSED` |
| T15 | 關機後開機續跑 | host=`just_booted`，日誌最後確認 checkpoint=step 300，遠端已釋放 | `RECONCILE` → `PAUSED`；續跑 `resume_from`=step 300；不從 0 重跑 |
| T16 | 開機後遠端查不到 | host=`just_booted`，probe=failed | 維持 `UNKNOWN`；不重啟、不釋放；通知人 |
| T17 | 開機後已完成批次不重跑 | 批次 1～22 已驗 sha256，23～25 未下載 | `COLLECTING` 只收 23～25（遠端仍可取時）；否則標遺失並從 23 起排續跑 |
| T18 | 下載 sha256 不符 | 1 檔不符，重試次數未用完／已用完 | 未用完：重新下載；已用完：`ESCALATE` |
| T19 | 釋放後回查非 0 | release_check=`active_nonzero` | `RECHECK_RELEASE`；狀態 `RELEASE_UNCONFIRMED`；不得顯示完成 |
| T20 | 佇列空但訓練仍在跑 | 類 ComfyUI 佇列空，workload=training，step 前進中 | `CONTINUE`（佇列空不算閒置） |
| T21 | 最長時間到、checkpoint 剛確認 | elapsed=max，checkpoint 2 分鐘前確認 | `COLLECT` → `RELEASE`；`data_at_risk=false` |

測試要求：每條至少一個斷言檢查 `action`，並另外斷言「查詢失敗類情境絕不出現 `RELEASE`／`DONE`」（T01～T03、T16）。

---

## 5. 人用介面原型範圍（切片 ③，全假資料）

原則：中文、白話、把「下一步該做什麼」放在最顯眼的位置；危險動作二次確認；不顯示原始錯誤字串（先遮罩再顯示）。

| 畫面 | 內容 |
|---|---|
| 任務列表 | 每個 job 一列：名稱、類型（J1／J3／Wan）、狀態色塊（中文狀態名）、進度條（step 或批次）、已用／上限 CU、提交者（人／Bot）、人工鎖圖示 |
| 任務詳情 | 進度與最後心跳時間（JST）、最後確認 checkpoint、時間軸（每次狀態轉移與觸發者）、合約摘要 |
| 阻塞原因 | 一句白話＋建議動作按鈕，例如「下載第 23 批時雜湊不符，已重試 3 次。〔重試〕〔保存後停止〕」 |
| CU 面板 | 假資料：餘額、目前每小時耗用、此 job 已用／軟上限／硬上限、預估到上限時間；標示「示意數字，非真實額度」 |
| 產出與雜湊 | 每個產出檔：名稱、大小、sha256 前 8 碼、驗證結果（已驗／未驗／不符）、是否已落地 |
| 釋放狀態 | 明確分「已確認 0 active」與「釋放未確認」；後者用警示色，不顯示為睡眠 |
| 停止按鈕 | 兩個選項：「保存後停止（建議）」與「立即停止（可能遺失未保存產出）」；後者要再確認 |
| 本機狀態 | 在線／即將關機／剛開機核對中；關機前若有遠端工作，顯示需先收尾的清單 |
| 首次引導 | 三步說明：看列表、看阻塞原因、怎麼停 |

技術界線：靜態頁面加本機伺服器，只綁 127.0.0.1；所有資料來自假資料檔；不得含任何外部 URL 呼叫、憑證或私人路徑。按鈕只改假資料狀態並走同一個決策函式，用來展示轉移是否合理。

---

## 6. Bot 端口

### 6.1 允許的動作（白名單，其他一律拒絕）
| 動作 | 輸入 | 輸出 | 限制 |
|---|---|---|---|
| `list_jobs` | 可選狀態篩選 | job 摘要清單 | 不回傳憑證、不回傳原始日誌 |
| `get_status` | `job_id` | 狀態、進度、阻塞原因、`reason_code` | 同上 |
| `submit_job` | `template_id`＋範本允許的參數 | `job_id` 或拒絕理由 | 只能用登記範本；參數超出範本上下限即拒絕；不得自訂 `cu_cap` 高於範本值 |
| `request_pause` | `job_id` | 接受／拒絕 | 只走「保存後暫停」；有人工鎖則拒絕 |

第一期不給 Bot：立即停止、釋放、改上限、解人工鎖、讀檔、執行指令、改範本。續跑（`resume`）是否開放給 Bot，列入待決（建議：只對無人工鎖、`submitted_by` 為 Bot 自己的 job 開放）。

### 6.2 傳輸與安全
- 本機伺服器**只聽 127.0.0.1**，不綁 0.0.0.0、不開防火牆例外、不做通道轉發。
- 遠端執行的 Bot 無法直接連到本機的 127.0.0.1；實際呼叫方式是 Bot 透過已登記的本機指令通道，在本機上發出本機請求。這代表本機離線時端口自然不可用，與「關機即暫停」一致。
- 每個請求寫入 append-only 稽核紀錄：時間（JST）、呼叫者、動作、參數摘要、結果。
- 錯誤回應只回 `reason_code` 與中文訊息，不回原始例外字串。
- 請求限速，防止例行迴圈連打。

### 6.3 授權方式（待擁有者決定）
| 選項 | 說明 | 風險 |
|---|---|---|
| A. 只靠 127.0.0.1 | 不另設驗證 | 本機上任何本機程序都能呼叫 |
| B. 本機權杖檔＋使用者限定 ACL（建議） | 權杖只存在本機、限目前使用者讀取，不進 repo、不進日誌；可輪替 | 要管理一個本機祕密 |
| C. Windows 具名管道＋使用者 ACL | 不走 TCP | 實作與測試較複雜，跨機器呼叫更麻煩 |
| D. 提交需人在介面確認 | Bot 的 `submit_job` 先進「待人確認」 | 最安全，但例行不能無人值守 |

---

## 7. 分期切片

`workbench/` 是工作台根目錄。`tools/ci_run_gates.py` 以**完全相同的路徑**比對 `expected_paths`，不支援萬用字元，所以每片都要列出確切檔名。

### ① 規格（本單 009）
- expected_paths：`specs/009-local-workbench.md`（只寫在這裡，不放表格列）。
- 完成條件：見下方「Definition of done（切片 ①）」。
- 分工：Clau小羊寫規格；Gro小貓驗收合併。

### ② 停機決策函式＋單元測試（工單 010，後續開單）
- expected_paths（暫定，010 spec 定稿為準）：`specs/010-workbench-stop-policy.md`、`tools/check_010.py`、`workbench/stop_policy.py`、`workbench/tests/test_stop_policy.py`、`workbench/fixtures/scenarios.json`（假資料）。
- 測試指令（暫定）：repo 根跑 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workbench python -m unittest discover -s workbench/tests` exit 0。
- 閘門（Gpt小豬寫 `tools/check_010.py` 並在 lock 記 010）至少檢查：
  - 第 4.5 節每條情境都有對應測試且通過，至少 12 條；
  - 查詢失敗類情境（T01～T03、T16）絕不輸出 `RELEASE`／`DONE`；
  - 突變必須紅：例如把「查詢失敗」當閒置、拿掉人工鎖檢查、硬上限跳過寬限，各至少讓一個測試失敗；
  - `stop_policy.py` 不匯入網路、子程序、檔案寫入相關模組，不讀系統時鐘；
  - 只用標準函式庫；
  - 不含 URL、token 樣式字串、私人路徑；
  - 回歸：`check_001.py`～`check_008.py` 仍 exit 0。
- 完成條件：`python tools/check_010.py` exit 0、最後一行 `RESULT: ALL PASS`；實作 PR head 上 `gate` job 綠（選到 010、`scope: PASS`、`lock: PASS`）；Gro小貓驗收合併。
- 分工：Gpt小豬閘門與鎖 → Gemi小狗實作 → Gro小貓驗收。

### ③ 假資料介面原型（工單 011，後續開單，② 合併後才開）
- expected_paths（暫定，011 spec 定稿為準）：`specs/011-workbench-mock-ui.md`、`tools/check_011.py`、`workbench/ui/index.html`、`workbench/ui/app.js`、`workbench/ui/style.css`、`workbench/ui/fixtures/jobs.json`、`workbench/serve_local.py`（只綁 127.0.0.1）。
- 閘門至少檢查：
  - 綁定位址只有 127.0.0.1；
  - 前端不含外部網址請求；
  - 第 5 節每個畫面元素存在且為中文標籤；
  - 假資料 CU 面板有「示意數字」標示；
  - 「釋放未確認」不會被渲染成完成；
  - 停止按鈕有兩個選項，且立即停止需確認；
  - 狀態轉移經 `serve_local.py` 呼叫 ② 的 `stop_policy.decide`，而非另寫一套。
- 完成條件：`python tools/check_011.py` exit 0；擁有者在本機開一次原型給意見（可選，不阻擋合併）。
- 分工：同 ②。

### ④ 接真 Colab（本期不做，另批）
開工前必須另外取得擁有者核准，且先完成：
1. 查清官方支援的操作介面；不使用非公開端點。
2. 憑證保管方案（不得明文落地、日誌統一遮罩、可撤銷）。
3. **遠端端自我守衛**：遠端工作自己帶時間與預算上限、定期 checkpoint，不依賴本機在線；本機離線時遠端如何安全暫停，要有實測證據。
4. 小額實跑計畫（單一 job、CU 上限、成功與失敗條件）與回滾方式。
5. 不影響現行瀏覽器操作的 Colab 例行。
6. 真實設定與祕密一律不進 hello；需要私人 repo 時另請擁有者核准。

---

## 8. 待決清單

1. **人工與 Bot 的優先**：本規格預設「人與 Bot 控制同一批工作、人工停止優先、人可以搶停 Bot 工作、Bot 不能搶停人的工作」。另待決：Bot 是否可續跑自己提交的暫停工作。
2. **Colab 操作方式**：繼續用瀏覽器操作，或研究受控端口。本規格不預先核准任何端點、權限或憑證方案；切片 ④ 才談。
3. **首期工作類型**：本規格預設 J1／J3／WAN；是否納入其他類型待決。
4. **CU 上限與衝突優先**：每份工作與每期的上限；預算硬停與保進度衝突選 A／B／C（建議 C）；狀態不明時撞到硬上限是否允許自動停。
5. **產出保存位置**：產出與 checkpoint 存哪裡、保留幾個、多久。
6. **Bot 端口授權方式**：第 6.3 節 A～D（建議 B）。
7. **遠端工作在本機關機時的預設**：`pause_safely`（建議）或 `continue_until_checkpoint`。
8. **repo 位置**：**已決：hello 子目錄（2026-11-09）**。切片 ①～③ 放 `workbench/`；切片 ④ 若需要真實設定，另議。
9. **既有任務限制是否沿用**：舊計畫中的內容限制，是否套用到工作台所有工作類型。

---

## 9. 風險與已知缺口
- 本機有沒有 GPU、能否長時間開機、是否已有 Python，都沒核實；②③ 的閘門在 CI 或雲端 agent 上跑，不依賴本機。
- 「釋放後 0 active」目前只有瀏覽器畫面證據，沒有程式介面證據；切片 ④前，真實釋放確認方式未定。
- 心跳要求工作本身回報 step／批次；現有 notebook 尚無這個機制，切片 ④要另外補。
- 介面顯示的 CU 在切片 ③全是假資料；真實扣點只能以官方資源面板為準。
- 本規格未查官方 Colab 支援的程式介面；不能據此宣稱任何介面可用或不可用。

---

---

## Definition of done（切片 ①）

1. 本 PR diff（相對 main，三點 diff）的檔案集合 == {`specs/009-local-workbench.md`}。
2. PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠：沒有碰到任何工單路徑 → regression 跑 001～008 全綠，`scope: PASS`、`lock: PASS`、`CI RESULT: PASS`。
3. 本檔沒有任何第一格含 `expected_paths` 的表格列。
4. 本檔不含私人路徑（沙盒或使用者家目錄的絕對路徑、Windows 磁碟機路徑）、電子郵件地址、token 樣式字串、機器名稱或真實額度數字。
5. Gro小貓驗收合併。

## 不做的事

- 不新增 `workbench/` 底下任何檔案（留給 010、011）。
- 不改 `src/`、`tests/`、`tools/`、`.github/`、`fixtures/`，不改 lock。
- 不加 pip 依賴，不上網，不接任何真實服務。
- 不把 `gate` 設成 required（repo 設定由擁有者決定）。
