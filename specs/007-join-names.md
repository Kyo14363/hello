# Work order 007 - 把多個名字接成一句

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-10-27）。第一張只新增檔案、不碰 `src/hello.py` 的實作單。兩張 PR：先 spec＋閘門＋鎖，再實作 |
| Repo | https://github.com/Kyo14363/hello |
| Implementer | spec **Clau小羊**；閘門與鎖 **Gpt小豬**；實作 **Cursor 雲端 agent**（試用）；驗收與合併 **Gro小貓** |
| expected_paths | `specs/007-join-names.md`、`tools/check_007.py`、`src/names.py`、`tests/test_names.py` |
| Definition of done | `python tools/check_007.py` exits 0，且實作 PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠 |

## 要做的事

新增 `src/names.py`，裡面有一個函式 `join_names(names)`，把一串名字接成一句英文：

```python
>>> from names import join_names
>>> join_names(["Kyo", "Gitmy", "Ami"])
'Kyo, Gitmy and Ami'
```

再新增 `tests/test_names.py` 測它。只有這兩個新檔，不改任何既有檔。

## 規則

### R1 `join_names(names)` 的行為

- `names` 是一個可迭代物件，元素都是 `str`。list 和 tuple 都要能用。
- 每個元素先去掉前後空白（`str.strip()`）。去完是空字串的元素丟掉。
- 剩下的名字照原順序接起來，重複的名字保留：
  - 0 個：回傳 `""`
  - 1 個：回傳那個名字
  - 2 個：`"A and B"`
  - 3 個以上：最後兩個用 `" and "` 接，其餘用 `", "` 接，例如 `"A, B, C and D"`。`and` 前面不加逗號。
- 回傳 `str`，不 print，不寫檔。
- 不改呼叫者傳進來的 list。
- `names` 本身是 `str` 或 `bytes` 時 raise `TypeError`（不准把一個字串拆成字母）。
- 有任何元素不是 `str` 時 raise `TypeError`。

對照表（閘門 G2 逐列比對，`==` 完全相等）：

| 輸入 | 回傳 |
|------|------|
| `[]` | `""` |
| `["Kyo"]` | `"Kyo"` |
| `["Kyo", "Gitmy"]` | `"Kyo and Gitmy"` |
| `("Kyo", "Gitmy")` | `"Kyo and Gitmy"` |
| `["Kyo", "Gitmy", "Ami"]` | `"Kyo, Gitmy and Ami"` |
| `["A", "B", "C", "D"]` | `"A, B, C and D"` |
| `["  Kyo ", "", "   ", "Gitmy"]` | `"Kyo and Gitmy"` |
| `["", " "]` | `""` |
| `["Kyo", "Kyo"]` | `"Kyo and Kyo"` |

| 輸入 | 結果 |
|------|------|
| `"Kyo"` | `TypeError` |
| `b"Kyo"` | `TypeError` |
| `["Kyo", 3]` | `TypeError` |
| `["Kyo", None]` | `TypeError` |

### R2 寫法限制

- `src/names.py` 只用標準庫，不上網、不讀環境變數、不讀寫檔。
- `src/names.py` 不 import `hello`。本單要能獨立運作，以後改 `src/hello.py` 不會牽動本單。
- import `names` 時不得有輸出。
- 模組頂層要有 `def join_names(names):`，剛好一個位置參數，沒有預設值。可以另加私有輔助函式。

### R3 測試

- 新增 `tests/test_names.py`，用標準庫 `unittest`，不引 pytest、不加 pip 依賴。用 `from names import join_names` 匯入。
- 在 repo 根跑 `PYTHONPATH=src python -m unittest tests.test_names` 必須退出 0。
- 至少涵蓋：0 個名字、1 個、2 個、3 個以上、前後空白與空字串被丟掉、`names` 是 `str` 時 raise `TypeError`。每一項至少一個 `assertEqual` 或 `assertRaises`。
- 不改 `tests/test_hello.py`。

## 範圍與 PR 形狀（CI 會怎麼判）

`tools/ci_run_gates.py` 用**整張 PR 的 diff** 判範圍，不是逐 commit 判。規劃時在本機用 `ci_run_gates.py --base <main> --head <branch> --dry-run` 模擬過兩張 PR：

- spec 列了 `tools/check_007.py`，那個檔不在時 `discover()` 直接報錯（`CI GATE ERROR`，exit 2）。所以 spec 不能單獨開 PR，要和閘門一起。
- 有 `check_007.py`、lock 卻沒有 007，會 `lock: FAIL`。所以閘門和 lock 同一張 PR。
- 本單的 `expected_paths` 不含 `src/hello.py`、`tests/test_hello.py`，所以兩張 PR 都**不會**選到 003、004、006，只跑 007。
- 因為四個檔都在 007 的清單裡，就算合成一張 PR，scope 也會過。仍拆成兩張，是要讓 spec 和閘門先進 main、閘門先證明會咬人，實作臂只拿到已合併的 spec 和 `expected_paths`。

### PR A：spec＋閘門＋鎖（先合）

- 只改 `specs/007-join-names.md`（Clau小羊）、`tools/check_007.py` 和 `tools/gate_acceptance_lock.json`（Gpt小豬）。lock 是基礎建設檔，不算範圍。
- 在 lock 為 007 新增一筆 initial acceptance，記 `check_sha256` 和本檔 `expected_paths` 那一列的 `spec_row_sha256`。不改 001–006 的紀錄。
- 預期：選到 `007`，`scope: PASS`，`lock: PASS`，`check_007` 紅（還沒實作）。紅只能來自 G1–G4；scope、lock 或 G5 紅就退回。這和 006 的 PR #59 同一種情形：spec＋閘門 PR 在實作前合，`gate` 是紅的。

### PR B：實作（PR A 合進 main 後才開）

- Cursor 雲端 agent 從含 PR A 的 main 開分支，只新增 `src/names.py` 和 `tests/test_names.py`。
- 預期：選到 `007`，`scope: PASS`，`lock: PASS`，`check_007` 綠，`CI RESULT: PASS (1 gate(s))`。
- 多碰任何一個檔就紅。例如順手改 `tests/test_hello.py`，會同時選到 003、004、006，而且那個檔不在 007 的清單裡，`scope: FAIL`。改 `README.md` 不算違規（基礎建設），但本單不需要，不要改。
- 不加 `tests/__init__.py`、`src/__init__.py`、artifacts、log。agent 的證據貼在 PR 留言，不進 diff。
- hello 沒有 `.gitignore`。本機跑過測試後 `src/__pycache__/`、`tests/__pycache__/` 會冒出 `.pyc`，用 `git add -A` 會一起進 diff，落在清單外，`scope: FAIL`。只 `git add src/names.py tests/test_names.py`，或跑測試時設 `PYTHONDONTWRITEBYTECODE=1`。規劃模擬時真的踩到過一次。

## 閘門（給 Gpt小豬）

`tools/check_007.py` 用標準庫、離線、ASCII stdout，子程序設 `PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`，並洗掉 `PYTHONPATH` 等會漏進子程序的環境再自己設 `PYTHONPATH=src`。活檔只讀，突變一律在暫存複本。每項印 `[PASS]`、`[FAIL]` 或 `[BLOCKED]`，結尾印 `RESULT: ALL PASS` 或 `RESULT: FAIL`，有一項不是 PASS 就 exit 1。

- **G1 形狀**：`src/names.py`、`tests/test_names.py` 存在。用 `ast` 讀 `src/names.py`：頂層有 `join_names`，剛好一個位置參數、沒有預設值、沒有 `*args`／`**kwargs`；沒有 `import hello`／`from hello`；import 的模組都在標準庫且不是網路模組（`socket`、`urllib`、`http`、`ssl`、`requests` 等）。子程序 `import names` 的 stdout 是空的。
- **G2 行為**：在子程序 import `names`，逐列跑 R1 的兩張對照表，回傳值 `==` 完全相等、例外型別是 `TypeError`。另外確認呼叫後傳入的 list 內容不變。
- **G3 測試全綠**：`PYTHONPATH=src python -m unittest tests.test_names` 退出 0，而且跑到的測試數 ≥ 4。
- **G4 突變必須紅**：在暫存複本對 `src/names.py` 分別換上下面三個突變版的 `join_names`，每一個都要讓 `tests.test_names` 至少一個測試失敗：
  - M1 牛津逗號：3 個以上時回傳 `"A, B, and C"`。
  - M2 不去空白、不丟空字串。
  - M3 `names` 是 `str` 時不 raise，直接當成字元序列處理。
- **G5 回歸與活檔不動**：同一棵樹上 `python tools/check_006.py` exit 0（它會再跑 003、004）。跑 G1–G5 前後對 repo 內所有檔（略過 `.git`、`__pycache__`）算 sha256，前後必須一樣。

在 PR A（還沒實作）上，G1 必須紅，證明閘門會咬人；G5 必須綠。

## 不做的事

- 不改 `src/hello.py`、`tests/test_hello.py`，也不讓 `hello.py` 呼叫 `join_names`（那會改到 003、004、006 的檔，另開單）。
- 不改 `tools/check_001.py` 到 `tools/check_006.py`、`tools/ci_run_gates.py`、`.github/`。
- 不改 lock 裡 001–006 的紀錄。
- 不加 pytest 或任何 pip 依賴，不上網。
- 不把 `gate` 設成 required（那是 repo 設定，要奈 神決定）。
