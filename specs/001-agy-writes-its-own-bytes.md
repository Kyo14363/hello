# Work order 001 - agy 自己讀到、寫進本來沒有的位元組

| Field | Content |
|------|---------|
| Status | spec 完成,待閘門與實作(2026-09-01) |
| Repo | https://github.com/Kyo14363/hello （測試區；**不得**帶回 kyo-work） |
| Upstream | Gemi 自查：agy ping 綠（`GEMINI_FLASH_OK`），但 headless 改檔被擋 `read_file`；Grok CLI 想完 `cancelled`、檔沒寫進去。015–017 才落到頻道這條直接改。本單證明「能編碼」不是 ping。 |
| Implementer | 閘門由 **Gpt小豬 / Luna** 寫；實作由 **Gemi小狗** 只透過 **agy**（`gemini-3.7-flash-high`，effort high）動手；驗收與合併 **Gro小貓**。本頻道代改目標檔 = 紅。 |
| Delivery location / expected_paths | `specs/001-agy-writes-its-own-bytes.md`、`tools/check_001.py`、`src/agy_wrote.txt`、`artifacts/agy-001.json`、`artifacts/agy-001.log` |
| Definition of done | `python tools/check_001.py` exits 0 |

kyo-work 的 ledger / 入口 / 宣告帳本**不進本倉**。本單自己有一支閘門就夠。

## Background

`hello` 幾乎是空的：`README.md`、`src/hello.py`（問候語 `Hello, Gitmy!`）。當測試區夠乾淨。

失效點不是 ping。agy `1.1.23` 在畚箕上 headless 時，`read_file` 會停在權限提示；沒有 `--mode accept-edits`（或同等自動准許），print mode 會等到 timeout / cancelled，磁碟不變。Gemi 用 Grok Bot 自己的 Shell 代改，看起來像交了貨，其實模型沒碰到檔。

本單只買一件事：**agy 行程自己讀到 `src/hello.py`，並寫進一個 main 上本來沒有的檔。**

## Requirements

### R1 模型與呼叫鎖死

Gemi 必須在畚箕、在 `hello` 工作目錄，用**這一條**（可加 `--print-timeout`，其餘旗標不得偷偷換模型）：

```
agy --model gemini-3.7-flash-high --effort high --mode accept-edits --output-format json --log-file artifacts/agy-001.log -p "<prompt>"
```

- stdout（json）存成 `artifacts/agy-001.json`。
- 若 `accept-edits` 仍在 `read_file` 停住，允許**另外**加上 `--dangerously-skip-permissions`，並在 PR 敘述寫明。不得改用 grok CLI、不得改用 `gemini-3.7-flash-medium` / low、不得改用 Claude。
- `--sandbox` 本單不開（它限制 terminal，不是這次要驗的）。

### R2 agy 必須讀到活檔

prompt 必須要求 agy **讀** `src/hello.py`。寫出的見證字串要含檔裡那句問候 `Hello, Gitmy!`（含逗號與驚嘆號，不含假設）。沒讀到就編造問候語 = 紅。

### R3 agy 必須寫進本來沒有的位元組

main 上沒有 `src/agy_wrote.txt`。交付後這個檔必須存在，且至少兩行：

1. 從 `src/hello.py` 讀到的問候語（見 R2）
2. 一行字面值 `agy-model: gemini-3.7-flash-high`

不得只改 `src/hello.py`、不得只改 README。新檔本身就是那一個本來沒有的位元組序列。

### R4 頻道代改算紅

下列任一成立，閘門必須紅：

- `src/agy_wrote.txt` 在磁碟上，但 `artifacts/agy-001.log` 與 `artifacts/agy-001.json` **都沒有**對應的讀 `src/hello.py` 與寫 `src/agy_wrote.txt` 紀錄
- 目標檔是 Grok Bot / 本頻道 / `git apply` / 人工貼上，agy 行程沒寫過
- 只有 ping 紀錄、沒有 write

Gemi 的 Grok Bot **不得**用自己的 Shell/Read/Write 去寫 `src/agy_wrote.txt`。那兩份 artifact 也必須是那一次 agy 呼叫的 stdout / log-file，不得事後手寫一份假 json。

### R5 閘門要能在暫存副本上證明代改會紅

`tools/check_001.py`（Luna 寫，實作臂不得改）：

- **G1** 活樹上 `src/agy_wrote.txt` 含 R3 那兩行，且 `src/hello.py` 仍含 `Hello, Gitmy!`
- **G2** artifact 證明同一趟 agy 讀了 `src/hello.py`、寫了 `src/agy_wrote.txt`，模型是 `gemini-3.7-flash-high`
- **G3** 自己構造的暫存副本：只放目標檔、拿掉 log/json 裡的 write（或整份 artifact）→ G2 必須紅。只驗「檔在」等於准許代改
- stdlib only、離線、ASCII stdout

log/json 的實際鍵名以 agy `1.1.23` 為準；Luna 寫閘門前可對一份真實 `--output-format json` 樣本對鍵，**不要**發明一份假 schema 再逼 Gemi 去符合。

## Out of scope

- kyo-work、ledger、工單 018、F7、required check
- 修 grok CLI 的 `cancelled`（另一座山）
- 把 agy 設成之後所有倉的唯一實作路徑
- 改 `src/hello.py` 的問候語、重寫 README、動 `hello-github-starter/`
- 在 CI 跑 agy（沒有 Gemini 權杖、也不該有）

## 交付順序

1. **本 PR：spec only。** 只有 `specs/001-agy-writes-its-own-bytes.md`。
2. **閘門 PR（小豬）：** `tools/check_001.py`。
3. **實作 PR（小狗）：** 用 R1 那條 agy 產出 `src/agy_wrote.txt` + 兩份 artifact。不得改閘門。
4. **驗收（小貓）：** `python tools/check_001.py` 退出 0；抽 artifact 對一下不是手寫的；合。

## Implementation notes（指引，不是契約）

- print mode 預設 timeout 5 分鐘；讀寫兩步通常夠，不夠就 `--print-timeout 10m`。
- 先 `mkdir artifacts` 再跑，避免 log-file 因目錄不存在而失敗。
- prompt 寫死路徑與兩行格式，別讓模型自由發揮檔名。
