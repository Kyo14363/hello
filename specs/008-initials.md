# Work order 008 - 從名字取縮寫

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-11-03 JST）。本 PR **只含 spec**；閘門、鎖、實作各自後續 PR |
| Repo | https://github.com/Kyo14363/hello （**不得**帶回 kyo-work） |
| Upstream | 007 新增獨立模組 `src/names.py` 的 `join_names()`。008 照同一個模式再加一個獨立小模組 |
| Implementer | spec **Clau小羊**；閘門與鎖 **Gpt小豬**；實作 **Cursor 雲端 agent**；驗收與合併 **Gro小貓** |
| expected_paths | `specs/008-initials.md`、`tools/check_008.py`、`src/initials.py`、`tests/test_initials.py` |
| Definition of done | 見下方「Definition of done」各條，全部可由程式判定 |

> ⚠ 本檔刻意**不放** `expected_paths` 表格列。`tools/ci_run_gates.py` 的 `discover()` 一看到 spec 表格裡有 `expected_paths` 列，就要求 `tools/check_008.py` 已存在，否則 `CI GATE ERROR`（exit 2）。本 PR 不含閘門，所以 `expected_paths` 先寫在下面的清單；**閘門 PR（Gpt小豬）要把它移進上方表格成一列**，並在 lock 記 008 的 initial acceptance。

## expected_paths（閘門 PR 時移進表格）

實作 PR 的 diff 只能落在 `src/initials.py`、`tests/test_initials.py`。

## 要做的事

新增 `src/initials.py`，裡面有一個函式 `initials(name)`，回傳名字每個字的第一個字母（大寫）：

```python
>>> from initials import initials
>>> initials("Kyo Gitmy")
'KG'
```

再新增 `tests/test_initials.py` 測它。只有這兩個新檔，不改任何既有檔。

## 規則

### R1 `initials(name)` 的行為

- `name` 必須是 `str`，否則 raise `TypeError`（含 `bytes`、`None`、`list`）。
- 以 `str.split()`（無參數，任何空白都算分隔、連續空白視為一個）切字。
- 每個字取第一個字元，`str.upper()` 後照原順序接起來。
- 字裡的 `-` 不切開（`"Jean-Luc"` 只算一個字 → `"J"`）。
- 空字串或全空白回傳 `""`。
- 回傳 `str`，不 print，不寫檔。

對照表（閘門 G2 逐列比對，`==` 完全相等）：

| 輸入 | 回傳 |
|------|------|
| `"Kyo Gitmy"` | `"KG"` |
| `"kyo gitmy"` | `"KG"` |
| `"Kyo"` | `"K"` |
| `"  Kyo   Gitmy  Ami "` | `"KGA"` |
| `"Kyo\tGitmy\nAmi"` | `"KGA"` |
| `"Jean-Luc Picard"` | `"JP"` |
| `""` | `""` |
| `"   "` | `""` |

| 輸入 | 結果 |
|------|------|
| `b"Kyo"` | `TypeError` |
| `None` | `TypeError` |
| `["Kyo"]` | `TypeError` |

### R2 寫法限制

- `src/initials.py` 只用標準庫，不上網、不讀環境變數、不讀寫檔。
- 不 import `hello`、`names`（獨立運作，不牽動 003、004、006、007）。
- import `initials` 時不得有輸出。
- 模組頂層有 `def initials(name):`，剛好一個位置參數、沒有預設值、沒有 `*args`／`**kwargs`。可另加私有輔助函式。

### R3 測試

- 新增 `tests/test_initials.py`，標準庫 `unittest`，不引 pytest、不加 pip 依賴；用 `from initials import initials`。
- repo 根跑 `PYTHONPATH=src python -m unittest tests.test_initials` 退出 0。
- 至少涵蓋：兩個字、小寫轉大寫、多餘空白、空字串、非 `str` raise `TypeError`。每項至少一個 `assertEqual` 或 `assertRaises`。

## Definition of done（全部可機器判定）

1. `python tools/check_008.py` exit 0，最後一行 `RESULT: ALL PASS`。
2. 實作 PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠：選到 `008`、`scope: PASS`、`lock: PASS`、`CI RESULT: PASS`。
3. 實作 PR diff（相對 main，三點 diff）的檔案集合 == {`src/initials.py`, `tests/test_initials.py`}。
4. `PYTHONPATH=src python -m unittest tests.test_initials` exit 0，跑到的測試數 ≥ 5。

## 閘門（給 Gpt小豬，本 PR 不寫）

`tools/check_008.py` 沿用 007 的寫法：標準庫、離線、ASCII stdout，子程序設 `PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`、自設 `PYTHONPATH=src`；活檔只讀，突變在暫存複本；每項印 `[PASS]`／`[FAIL]`／`[BLOCKED]`，結尾 `RESULT: ALL PASS` 或 `RESULT: FAIL`。

- **G1 形狀**：兩檔存在；`ast` 確認 R2 的簽名與 import 限制；`import initials` stdout 為空。
- **G2 行為**：逐列跑 R1 兩張對照表。
- **G3 測試全綠**：R3 指令 exit 0，測試數 ≥ 5。
- **G4 突變必須紅**：M1 不轉大寫；M2 用 `split(" ")`（多餘空白會產生空字串而出錯或多字）；M3 `bytes` 不 raise。每個突變都要讓 `tests.test_initials` 至少一個測試失敗。
- **G5 回歸與活檔不動**：`python tools/check_007.py`、`python tools/check_006.py` exit 0；前後對 repo 檔（略 `.git`、`__pycache__`）算 sha256 不變。

## 範圍與 PR 形狀（CI 會怎麼判）

`tools/ci_run_gates.py` 用**整張 PR 的 diff** 判範圍。

- **PR A（本 PR，spec only）**：只改 `specs/008-initials.md`。spec 沒有 `expected_paths` 表格列 → `discover()` 略過本檔；diff 不碰任何 001～007 的 `expected_paths` → regression 模式跑全部 001～007 閘門，應與 main 同為綠。已於 2026-11-03 JST 本機用 `--base main --head <branch>` 模擬。
- **PR B（閘門＋鎖，Gpt小豬）**：把 expected_paths 移進表格、加 `tools/check_008.py`、lock 加 008。預期選到 008、scope／lock PASS、`check_008` 紅（尚未實作，G1 紅、G5 綠）。
- **PR C（實作，Cursor 雲端 agent，PR B 合進 main 後才開）**：只新增 `src/initials.py`、`tests/test_initials.py`。只 `git add` 這兩檔或設 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 進 diff 造成 `scope: FAIL`。證據貼 PR 留言，不進 diff。

## 不做的事

- 不改 `src/hello.py`、`src/names.py`、`tests/test_hello.py`、`tests/test_names.py`。
- 不改 `tools/check_001.py`～`check_007.py`、`tools/ci_run_gates.py`、`.github/`，不改 lock 裡 001～007 的紀錄。
- 不加 pytest 或任何 pip 依賴，不上網。
- 不把 `gate` 設成 required（repo 設定由奈 神決定）。
