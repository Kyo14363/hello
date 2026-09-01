# Work order 002 - headless 讀檔要靠 skip-permissions，不是 accept-edits

| Field | Content |
|------|---------|
| Status | spec 完成,待閘門與實作(2026-09-01) |
| Repo | https://github.com/Kyo14363/hello （**不得**帶回 kyo-work） |
| Upstream | 001 關了（#3 `2f2971e`，`check_001` ALL PASS）。Gemi 實測：`--mode accept-edits` 仍擋 `read_file`；加上 `--dangerously-skip-permissions` 才寫進 `src/agy_wrote.txt`。001 的 log 寫著 `toolPermission=request-review`，以及 `Print mode: --dangerously-skip-permissions set, auto-approving all tool permissions`，然後才有 `Always-proceed: auto-approving tool confirmation "ViewFile"`。 |
| Implementer | 閘門 **Gpt小豬 / Luna**；實作 **Gemi小狗** 只透過 **agy**（`gemini-3.7-flash-high`）；驗收 **Gro小貓**。頻道代改 = 紅。 |
| expected_paths | `specs/002-agy-headless-needs-skip-permissions.md`、`tools/check_002.py`、`src/agy_headless.txt`、`artifacts/agy-002.json`、`artifacts/agy-002.log` |
| Definition of done | `python tools/check_002.py` exits 0 |

⚠ **不得改** `tools/check_001.py`、`src/agy_wrote.txt`、`artifacts/agy-001.*`。001 已關。

## Background

agy `1.1.23` 的 `--mode accept-edits` 是 cycle mode，**不是**把 `ViewFile` / `read_file` 自動准掉。print mode 預設 `toolPermission=request-review`，headless 會停在權限提示——這就是 001 第一次失敗。

真正把 ViewFile 放行的是 `--dangerously-skip-permissions`（log 字面：`auto-approving all tool permissions`）。001 把它寫成「accept-edits 不夠時允許加」；本單把它**從後備改成必帶**，免得下一趟再撞一次五分鐘 timeout。

本單不修 agy.exe。本單把「能編碼的那條指令」釘死。

## Requirements

### R1 指令必帶 skip-permissions

Gemi 在畚箕、`hello` 工作目錄跑（可加 `--print-timeout`、可保留 `--mode accept-edits`，但**不可**拿掉 skip-permissions、不可換模型）：

```
agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions --output-format json --log-file artifacts/agy-002.log -p "<prompt>"
```

stdout 存 `artifacts/agy-002.json`。

`--mode accept-edits` **單獨出現不算過**。閘門認的是 log 裡那句 skip-permissions，不是 cycle mode。

### R2 再寫一個本來沒有的檔，證明食譜可重複

main 上沒有 `src/agy_headless.txt`。agy 必須自己讀 `src/hello.py`，寫進這個新檔，至少兩行：

1. `Hello, Gitmy!`（從 `src/hello.py` 讀到，不得編造）
2. 字面值 `agy-flag: dangerously-skip-permissions`

不得改 `src/hello.py`、不得改 001 的交付物。

### R3 頻道代改算紅

`src/agy_headless.txt` 在、但 `artifacts/agy-002.log` / `agy-002.json` 沒有讀 `src/hello.py` 與寫 `src/agy_headless.txt` = 紅。Gemi 的 Grok Bot 不得代寫目標檔或假 log。

### R4 閘門

`tools/check_002.py`（Luna 寫，實作臂不得改），stdlib / 離線 / ASCII stdout：

- **G1** 活樹 `src/agy_headless.txt` 含 R2 兩行；`src/hello.py` 仍含 `Hello, Gitmy!`；001 交付物仍在
- **G2** `agy-002.log` 含字面 `Print mode: --dangerously-skip-permissions set, auto-approving all tool permissions`，且同一趟有讀 `src/hello.py`、寫 `src/agy_headless.txt`，模型 `gemini-3.7-flash-high`
- **G3** 暫存副本：只放目標檔、拿掉 artifact 的 write → G2 紅（代改）
- **G4** 暫存副本：log 留著 `accept-edits`、刪掉 R1 那句 skip-permissions → G2 紅（001 的坑）

活檔只讀不寫。鍵名以 agy 1.1.23 真實 log 為準（001 已有樣本），不要發明 schema。

## Out of scope

- 修 agy 讓 accept-edits 也放行 ViewFile
- grok CLI `cancelled`、Antigravity 登入、kyo-work
- 改 `check_001.py` 或 001 交付物
- 在 CI 跑 agy
- 把 skip-permissions 寫進之後所有倉的預設（本單只鎖 hello 測試區）

## 交付順序

1. 本 PR：spec only（本檔）。
2. 閘門 PR：`tools/check_002.py`。
3. 實作 PR：R1 那條 agy 產出新檔 + 兩份 artifact。
4. 小貓：`python tools/check_002.py` 退出 0 再合。
