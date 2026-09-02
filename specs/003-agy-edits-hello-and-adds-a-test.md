# Work order 003 - agy 要改既有程式，不只是新寫一個檔

| Field | Content |
|------|---------|
| Status | spec 完成,待閘門與實作(2026-09-01) |
| Repo | https://github.com/Kyo14363/hello （**不得**帶回 kyo-work） |
| Upstream | 001 證明能寫新檔；002 把 `--dangerously-skip-permissions` 釘成 headless 必帶。兩邊都沒改 `src/hello.py`。本單才是「編碼」：agy 改既有檔，並補一支 stdlib 測試。 |
| Implementer | 閘門 **Gpt小豬 / Luna**；實作 **Gemi小狗** 只透過 **agy**（`gemini-3.7-flash-high` + skip-permissions）；驗收 **Gro小貓**。頻道代改 = 紅。 |
| expected_paths | `specs/003-agy-edits-hello-and-adds-a-test.md`、`tools/check_003.py`、`src/hello.py`、`tests/test_hello.py`、`artifacts/agy-003.json`、`artifacts/agy-003.log` |
| Definition of done | `python tools/check_003.py` exits 0 |

⚠ **不得改** `tools/check_001.py`、`tools/check_002.py`、001／002 的 `src/agy_*.txt` 與 `artifacts/agy-001.*` / `agy-002.*`。

⚠ **問候語字面值不得改。** `src/hello.py` 必須仍含 `Hello, Gitmy!`（001／002 的 G1 還在回歸）。

## Background

`src/hello.py` 現在只有 `main()` 直接 `print("Hello, Gitmy! 👋")`。001／002 的交付是旁邊多兩個見證檔。那證明接線，不證明能改程式。

本單要 agy 自己：

1. 讀並**改** `src/hello.py`（抽出 `greet()`，`main()` 改印 `greet()`）
2. 新增 `tests/test_hello.py`，用 stdlib `unittest` 斷言 `greet()` 回傳含 `Hello, Gitmy!` 的字串
3. 指令仍必帶 skip-permissions（002 食譜，不再當後備）

不引 pytest、不加第三方套件。閘門用 `python -m unittest`。

## Requirements

### R1 指令

畚箕、`hello` 工作目錄（可加 `--print-timeout`、可留 `--mode accept-edits`，不可拿掉 skip-permissions、不可換模型）：

```
agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions --output-format json --log-file artifacts/agy-003.log -p "<prompt>"
```

stdout 存 `artifacts/agy-003.json`。

### R2 改 `src/hello.py`

- 必須有可呼叫的 `greet()`，回傳值含字面 `Hello, Gitmy!`（emoji 可留在回傳值裡，與現況一致）。
- `main()` 必須呼叫 `greet()` 再印，不得再把問候語只寫在 `print("...")` 裡當唯一來源。
- 直接跑 `python src/hello.py` 行為仍是印出那句問候（回歸：stdout 含 `Hello, Gitmy!`）。
- **檔必須與 002 合後的版本有 diff。** 只新增測試、hello.py 原封 = 紅。

### R3 新增 `tests/test_hello.py`

- stdlib `unittest`。至少一筆測試呼叫 `greet()`，斷言回傳值含 `Hello, Gitmy!`。
- 匯入方式自便，但 `python -m unittest tests.test_hello`（在 repo 根）必須能收。
- 不得要求 pytest、pip install。

### R4 頻道代改算紅

目標檔在磁碟、但 `artifacts/agy-003.log` / `agy-003.json` 沒有讀寫 `src/hello.py` 與寫 `tests/test_hello.py` = 紅。Gemi 的 Grok Bot 不得代寫。

### R5 閘門

`tools/check_003.py`（Luna 寫，實作臂不得改），stdlib / 離線 / ASCII stdout：

- **G1** R2／R3 的形狀在活樹上；`Hello, Gitmy!` 仍在 `src/hello.py`；001／002 交付物仍在
- **G2** `agy-003.log` 含 `Print mode: --dangerously-skip-permissions set, auto-approving all tool permissions`，且同一趟有讀＋寫 `src/hello.py`、寫 `tests/test_hello.py`，模型 `gemini-3.7-flash-high`
- **G3** 暫存副本：檔在、拿掉 artifact 的 write → G2 紅
- **G4** `python -m unittest tests.test_hello` 退出 0；把 `greet()` 改壞的暫存副本上同一條測試必須紅（空測試不算）
- 啟動回歸前洗掉不該漏給子行程的環境；**回跑** `python tools/check_001.py` 與 `python tools/check_002.py`，兩者都必須仍綠

活檔只讀不寫（回歸與 G4 突變都在暫存副本）。log 鍵名跟 001／002 同一套 agy 1.1.23 樣本。

## Out of scope

- 改問候語、刪 emoji、重寫 README、動 `hello-github-starter/`
- 修 agy 讓 accept-edits 放行 ViewFile
- grok CLI、kyo-work、在 CI 跑 agy
- 加 pytest / 任何 pip 依賴

## 交付順序

1. 本 PR：spec only（本檔）。
2. 閘門 PR：`tools/check_003.py`。
3. 實作 PR：R1 那條 agy 改 hello.py、加測試、兩份 artifact。
4. 小貓：`python tools/check_003.py` 退出 0 再合。
