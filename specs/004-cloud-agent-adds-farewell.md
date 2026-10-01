# Work order 004 - 雲端 agent 實作，照標準流程過閘門

| Field | Content |
|------|---------|
| Status | spec 完成，待閘門與實作重驗（2026-10-01） |
| Repo | https://github.com/Kyo14363/hello （**不得**帶回 kyo-work） |
| Upstream | 003 抽出 `greet()`、加 `tests/test_hello.py`（stdlib unittest）。2026-10-01 試驗時，Cursor 雲端 agent 先開了實作 PR #48（加 `farewell()`），被小貓判 BLOCKED，因為還沒有 spec 和閘門。本單把那次試驗補成標準流程：spec → 閘門 → 實作重驗 → 驗收。 |
| Implementer | spec **Clau小羊**；閘門 **Gpt小豬**；實作 **Cursor 雲端 agent**（沿用 PR #48，必要時由小羊用同一個 agent 補改）；驗收與合併 **Gro小貓**。 |
| expected_paths | `specs/004-cloud-agent-adds-farewell.md`、`tools/check_004.py`、`src/hello.py`、`tests/test_hello.py` |
| Definition of done | `python tools/check_004.py` exits 0 |

⚠ **不得改** `tools/check_001.py`、`tools/check_002.py`、`tools/check_003.py`、`src/agy_*.txt`、`artifacts/`。

⚠ **`greet()` 行為不得改。** 回傳值仍含 `Hello, Gitmy!`，`python src/hello.py` 仍印出問候語（001～003 的回歸還在用）。

## Background

001～003 證明畚箕 agy 能寫檔、能改既有程式。004 換一條實作路線：交給 Cursor 雲端 agent，在它自己的 VM 上改、開 PR、附證據。這條路快，但 2026-10-01 的試驗跳過了 spec 和閘門。本單要確認：雲端 agent 的實作也能被我們自己的閘門擋住，而不是只看它自己附的證據。

另外，奈 神 2026-10-01 同意**只在 hello** 試「閘門全綠且影響小就自動合併」（見 R5）。kyo-work 不適用。

## Requirements

### R1 `farewell(name)`

- `src/hello.py` 有可呼叫的 `farewell(name)`，與 `greet()` 同一個檔、同一種寫法（回傳字串，不直接 print）。
- `farewell("Gitmy")` 的回傳值含字面 `Goodbye, Gitmy!`；換一個名字（例如 `"Kyo"`）回傳值含 `Goodbye, Kyo!`，不得寫死成單一名字。
- `main()` 與 `greet()` 行為不變。

### R2 測試

- 測試加在既有的 `tests/test_hello.py`，維持 stdlib `unittest`，不引 pytest、不加 pip 依賴。
- 至少一筆測試呼叫 `farewell()` 並斷言回傳值含 `Goodbye, <name>!`。
- 在 repo 根跑 `python -m unittest tests.test_hello` 必須能收、退出 0。

### R3 範圍

- 實作 PR 的 diff 只能落在 `src/hello.py` 與 `tests/test_hello.py`（spec 與閘門各自一張 PR）。
- 實作 PR 必須是 rebase／更新到含本 spec 與 `tools/check_004.py` 的 main 之後的版本。

### R4 閘門 `tools/check_004.py`

Gpt小豬 寫，實作方不得改。stdlib／離線／ASCII stdout，活檔只讀不寫，突變一律在暫存副本：

- **G1** 形狀：`src/hello.py` 有 `greet()` 與 `farewell(name)`；`Hello, Gitmy!` 仍在；001～003 的交付物仍在。
- **G2** 行為：import 後 `farewell("Gitmy")` 含 `Goodbye, Gitmy!`、`farewell("Kyo")` 含 `Goodbye, Kyo!`；`greet()` 仍含 `Hello, Gitmy!`；`python src/hello.py` stdout 仍含 `Hello, Gitmy!`。
- **G3** 測試有在擋：`python -m unittest tests.test_hello` 退出 0；暫存副本上把 `farewell()` 改壞（例如回傳空字串），同一條測試必須紅。空測試或沒呼叫 `farewell()` 的測試不算。
- **G4** 回歸：洗掉不該漏給子行程的環境後，回跑 `python tools/check_001.py`、`check_002.py`、`check_003.py`，三支都必須仍綠。
- 結尾印 `RESULT: ALL PASS` 或 `RESULT: FAIL`，失敗時退出碼非 0。

### R5 hello 限定的自動合併試驗

小貓在下列條件**全部**成立時，可以直接合實作 PR，不必再問奈 神：

- **AM1** 小貓自己在 PR head 上重跑 `python tools/check_004.py`，退出 0（不採信 PR 內文自附的結果）。
- **AM2** diff 只落在 R3 允許的兩個檔，增刪合計 ≤ 50 行。
- **AM3** `mergeable_state` 為 clean，沒有未處理的 review 意見。
- **AM4** 本單 spec 與 `tools/check_004.py` 都已合進 main。

任一條不成立 = BLOCKED，退回補件，不合。合完要在 work work 回報合併 SHA 與 AM1～AM4 的結果。**本條只適用 hello，不得套用到 kyo-work。**

## Out of scope

- 改問候語、刪 emoji、重寫 README
- 在 hello 加 CI 或 Bugbot（另開工單）
- agy、grok CLI、kyo-work
- 加 pytest 或任何 pip 依賴

## 交付順序

1. 本 PR：spec only（本檔）。
2. 閘門 PR：`tools/check_004.py`（Gpt小豬）。
3. 實作：PR #48 更新到最新 main 後重驗；不足之處由雲端 agent 在同一張 PR 補。
4. 小貓：照 R5 驗收；全綠可直接合，否則退回。
