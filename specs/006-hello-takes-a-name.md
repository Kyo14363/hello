# Work order 006 - hello.py 可以帶名字

| Field | Content |
|------|---------|
| Status | 新 CI（範圍檢查＋閘門鎖）上線後第一張實作單。一張 PR、三個依序的 commit：spec、閘門＋鎖、實作 |
| Repo | https://github.com/Kyo14363/hello |
| expected_paths | `specs/006-hello-takes-a-name.md`、`tools/check_006.py`、`src/hello.py`、`tests/test_hello.py` |
| Definition of done | `python tools/check_006.py` exits 0，且同一個 head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠 |

## 要做的事

`python src/hello.py Kyo` 印出 `Hello, Kyo! 👋`。不帶參數時行為不變，仍印 `Hello, Gitmy! 👋`。

## 規則

- `greet()` 不能加參數。`check_004` 的 G1 要求 `greet` 沒有參數，改了 004 會紅。新的行為放在新函式 `greet_name(name)` 或 `main(argv)` 裡，由實作臂決定。
- `greet()`、`farewell(name)` 的回傳值不變。
- 只吃第一個參數；多的參數忽略。參數是空字串時，當作沒帶參數。
- 只用標準庫，不上網。
- `tests/test_hello.py` 至少加一個測試：帶名字會得到 `Hello, <name>!`。既有兩個測試不刪不改。

## 範圍與 PR 形狀（新 CI 會怎麼判）

規劃時在本機用 `ci_run_gates.py` 試跑過，有兩件事決定了 PR 的形狀：

- spec 列了 `tools/check_006.py`，但那個檔不在，`discover()` 會直接報錯。所以 spec 不能單獨成一張 PR。
- 有了 `check_006.py`，但 lock 裡沒有 006，會 `lock: FAIL`（lock orders 001–005 != discovered 001–006）。所以閘門和 lock 要同一個 commit 落地。

因此本單只開**一張 PR**（分支 `wo-006-hello-takes-a-name`），依序三個 commit：

1. **spec**（Clau小羊）：只加本檔。
2. **閘門＋鎖**（Gpt小豬）：只改 `tools/check_006.py` 和 `tools/gate_acceptance_lock.json`（後者是基礎建設檔）。在 lock 裡為 006 新增一筆 initial acceptance，記 `check_sha256` 和本 spec 表格列的 `spec_row_sha256`。不改 001–005 的紀錄。這個 commit 上 `gate` 應該紅，而且只能紅在 check_006 的 G1–G3；scope 和 lock 必須 PASS。
3. **實作**（Gemi小狗）：只改 `src/hello.py` 和 `tests/test_hello.py`。這兩個檔同時列在 003、004、006 的 `expected_paths`，所以三張單的範圍檢查都會過。多改任何一個檔，例如加 `artifacts/agy-006.json`，就會落在 004 的清單外，`gate` 會紅。agy 的日誌和 json 不進 PR，貼在頻道或 PR 留言。

前一個 commit 沒推、沒在頻道宣告，下一個不動。Gro小貓 驗收時要看第 2 個 commit 的紅確實只紅在 G1–G3，第 3 個 commit 全綠，再合。

## 閘門（給 Gpt小豬）

`tools/check_006.py` 用標準庫、離線、ASCII stdout，子程序都設 `PYTHONIOENCODING=utf-8`。

- **G1** `python src/hello.py Kyo` 的 stdout 含 `Hello, Kyo!`；不帶參數仍含 `Hello, Gitmy!`；參數是空字串時也含 `Hello, Gitmy!`。
- **G2** `tests/test_hello.py` 用 unittest 跑全綠，而且至少有一個測試方法同時呼叫到帶名字的路徑、斷言 `Hello, `。
- **G3** 突變必須紅：在暫存複本把帶名字的路徑改成忽略名字，G2 那個新測試要失敗。活檔只讀。
- **G4** 回歸：`check_003.py`、`check_004.py` 在同一棵樹上 exit 0。

在第 2 個 commit（還沒實作）上，G1 必須紅，證明閘門會咬人。

## 不做的事

- 不碰 kyo-work。
- 不改 `tools/check_001.py` 到 `tools/check_005.py`、`tools/ci_run_gates.py`、`.github/`。
- 不把 `gate` 設成 required（那是 repo 設定，要奈 神決定）。
