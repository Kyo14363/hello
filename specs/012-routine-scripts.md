# Work order 012 - 例行步驟改腳本試做（版號核對、當日檔案在不在）

| Field | Content |
|------|---------|
| Status | spec 草稿（2026-11-17 JST）。本 PR **只含這份 spec**；閘門、鎖、實作各自後續 PR |
| Repo | https://github.com/Kyo14363/hello （程式放新子目錄 `routines/`） |
| Upstream | 擁有者 2026-11-17 核准「把兩個日更例行的機械步驟改成腳本試做」。與 001～011 互不相依，不 import `src/`、`workbench/` 任何模組 |
| Implementer | spec **Clau小羊**；閘門與鎖 **Gpt小豬**；實作 **Gemi小狗**（Cursor 雲端 agent）；驗收與合併 **Gro小貓** |
| Definition of done | 見下方「Definition of done」各條，全部可由程式判定 |

> ⚠ 本檔刻意**不放** `expected_paths` 表格列，閘門 PR 才把下方清單移進上方表格。做法與 008、010、011 相同（011：spec PR #70 → 閘門 PR #72 → 實作 PR #73）。

本單兩支腳本只做「讀」：一支讀一個公開 changelog 網頁比版號，一支依呼叫端給的樣板，看某資料夾裡今天的檔在不在。**接不接上例行、什麼時候接，由各例行的負責 Bot 在本單合併後自己決定，不在本單範圍。** 本檔所有網址、版號、日期、條目文字都是**假資料**。

## expected_paths（閘門 PR 時移進表格）

閘門 PR 在上方表格加一列：第一格寫 `expected_paths`，第二格依序列出下面七個路徑，各自用反引號包住、以「、」分隔（與 007、008、010、011 同格式）。`ci_run_gates.py` 以完全相同的字串比對，不支援萬用字元。

1. `specs/012-routine-scripts.md`
2. `tools/check_012.py`
3. `routines/changelog_version_check.py`
4. `routines/daily_file_presence.py`
5. `routines/fixtures/changelog_sample.html`
6. `routines/tests/test_changelog_version_check.py`
7. `routines/tests/test_daily_file_presence.py`

實作 PR 的 diff 只能落在後五個檔（3～7）。**不需要** `routines/__init__.py` 或 `routines/tests/__init__.py`：測試指令用 `PYTHONPATH=routines` 加 `unittest discover -s routines/tests`，與 010 的 `workbench/` 一樣沒有套件檔。多加任何檔（含 `__pycache__`、README、第二個 fixture）都會讓 CI `scope: FAIL`。

## 要做的事

1. 新增 `routines/changelog_version_check.py`（腳本 A）：讀一個 changelog 網頁，找出最新版號、日期與條目，跟呼叫端給的「上一版號」比，印一行 JSON（見 A1～A6）。
2. 新增 `routines/daily_file_presence.py`（腳本 B）：在 `--root` 底下，依呼叫端用 `--pattern` 給的順序，看今天的每個檔在不在，印一行 JSON（見 B1～B5）。腳本**沒有任何預設樣板**，真實資料夾結構只存在呼叫端，不進 repo。
3. 新增 `routines/fixtures/changelog_sample.html`：自己寫的假 changelog 頁，內容照 A3（**不得**複製任何真實網站的文字）。
4. 新增兩個測試檔（見 T1）。

只有這五個新檔，不改任何既有檔。

## 共同規則

### C1 執行環境

- 只用 Python 標準庫，不加 pip 依賴，不加 pytest（測試用 `unittest`）。Python 3.9 以上可跑，Linux 與 Windows 都要能跑。
- 從 repo 根執行：`python routines/changelog_version_check.py ...`、`python routines/daily_file_presence.py ...`。
- 匯入模組時不得有輸出、不得連網、不得讀檔；只有 `main()`（`if __name__ == "__main__":` 底下呼叫）才做事。
- 每支腳本提供 `main(argv=None) -> int`，回傳值就是 exit code；`if __name__ == "__main__": sys.exit(main())`。

### C2 只讀

- 兩支腳本**都不寫檔**：不開寫入模式、不建資料夾、不刪、不改名、不改權限、不寫暫存檔、不寫快取。
- 腳本 B **不讀檔案內容**，只用 `os.stat`／`Path.is_file()` 一類的中繼資料呼叫；不列目錄（不用 `listdir`、`scandir`、`glob`、`iterdir`、`walk`）。
- 腳本 A 只在 `--input-file` 時讀那一個檔；沒有 `--input-file` 時不讀任何本機檔。

### C3 輸出

- stdout 第一行是一行 JSON，`json.dumps(..., ensure_ascii=True, sort_keys=True)`，所以第一行一定是純 ASCII。
- 除了 A5 的 `--text-line` 之外，stdout 不得有其他行；診斷訊息不印（錯誤原因放進 JSON 的 `error`）。
- 有 `--text-line` 時，腳本在印之前呼叫 `sys.stdout.reconfigure(encoding="utf-8")`，讓 Windows 主控台也能輸出中文。
- argparse 自己的用法錯誤（缺必要參數等）照 argparse 預設 exit 2、印到 stderr，不另處理。

### C4 公開 repo 衛生

- 五個新檔不含電子郵件、絕對路徑（`/home/`、`/Users/`、`C:\` 一類）、token 樣式字串、真實帳號、機器名、館藏名、例行 id。
- 網址只准出現 `https://example.invalid/...`、`http://127.0.0.1:<埠>/...` 兩種形式（測試與 fixture 用）；腳本本身**不寫死**任何網址，`--url` 必填（或改用 `--input-file`）。

## 腳本 A：`routines/changelog_version_check.py`

### A1 參數

| 參數 | 必填 | 說明 |
|---|---|---|
| `--url URL` | 與 `--input-file` 二選一（argparse 互斥群組，必填） | 只接受 `http://`、`https://`。其他 scheme（含 `file://`、`ftp://`）→ exit 2，`error` 以 `bad_url` 開頭，且**不得**呼叫 `urlopen` |
| `--input-file PATH` | 與 `--url` 二選一 | 離線用：讀這個本機檔當網頁內容（UTF-8，`errors="replace"`）。讀不到 → exit 2，`error` 以 `read_failed` 開頭 |
| `--previous-version STR` | 是 | 上一份日報寫的版號，接受 `v1.2.3` 或 `1.2.3`。格式不對（含空字串）→ exit 2，`error` 以 `bad_previous_version` 開頭 |
| `--timeout SEC` | 否，預設 20 | 傳給 `urlopen` 的 timeout |
| `--text-line` | 否 | 見 A5 |

### A2 取頁

- 用 `urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hello-routines/1"}), timeout=timeout)`，必須經由**模組層**的 `urllib.request.urlopen` 呼叫（測試用 `unittest.mock.patch("urllib.request.urlopen")` 換掉）。
- 最多讀 8,000,000 bytes；超過 → exit 2，`error` 以 `too_large` 開頭。
- `HTTPError` → exit 2，`error` 以 `http_status` 開頭（後接狀態碼）；`URLError`、`OSError`、timeout → exit 2，`error` 以 `fetch_failed` 開頭。
- 內容用 UTF-8 解碼，`errors="replace"`。

### A3 解析規則（HTML）

頁面結構（fixture 必須照這個形狀寫，真實頁面假設也是）：

- 每一版是一個 `<article ...>` 區塊，到下一個 `<article` 或文件結尾為止。
- 區塊裡的日期：第一個 `<time ...>` 標籤的 `datetime` 屬性（屬性名不分大小寫，例如 `dateTime`），值是 `YYYY-MM-DD` 且是真實存在的日期。
- 區塊裡的版號：第一個 `<h2 ...>` 標籤的 `id` 屬性，值符合 `^v(\d+)\.(\d+)\.(\d+)$`。其他地方出現的版號文字（例如 `<a href="#v1.2.3">v<!-- -->1.2.3</a>`、「Also includes 1.2.2」）一律不算。
- 區塊裡的條目：每個 `<h3 ...>文字</h3>` 開一個段落（段名＝去標籤、`html.unescape`、收空白後的文字，例如 `New`、`Improved`、`Fixed`）；之後到下一個 `<h3` 之前的每個 `<li ...>...</li>` 是一條。條目文字＝把 `<li>` 內所有標籤換成一個空白、`html.unescape`、連續空白收成一個、去頭尾空白；結果為空字串的條目略過。
- 沒有 `<time>` 有效日期、或沒有合格 `<h2 id>` 的 `<article>` 區塊整塊忽略。
- 「最新版」是所有合格區塊中**版號數值最大**的那一個（三段整數比較，`2.10.0 > 2.9.10`），不是頁面上第一個。同一版號出現兩次 → exit 2，`error` 以 `parse_failed` 開頭。
- 一個合格區塊都沒有 → exit 2，`error` 以 `parse_failed` 開頭。

### A4 結果與 exit code

JSON 鍵**剛好** `version`、`date`、`changed`、`new_entries`、`error` 五個。

| 情況 | exit | `version` | `date` | `changed` | `new_entries` | `error` |
|---|---|---|---|---|---|---|
| 最新版 == 上一版 | 0 | `"vX.Y.Z"` | `"YYYY-MM-DD"` | `false` | `[]` | `null` |
| 最新版 < 上一版（頁面倒退） | 0 | 頁面上的最新版 | 該版日期 | `false` | `[]` | `null` |
| 最新版 > 上一版 | 10 | 頁面上的最新版 | 該版日期 | `true` | 見下 | `null` |
| 任何讀不到、解析失敗、參數錯（A1、A2、A3 的錯誤） | 2 | `null` | `null` | `false` | `[]` | 非空字串，以上面列的代碼開頭 |

- `version` 一律帶 `v` 前綴，取自頁面，**絕不**拿 `--previous-version` 回填（exit 2 時尤其不行）。
- `new_entries`：所有版號**大於**上一版的合格區塊的條目，順序＝區塊在頁面上的順序、區塊內文件順序。每個元素是物件，鍵剛好 `version`（`"vX.Y.Z"`）、`section`（段名）、`text`（條目文字）。

### A5 `--text-line`

在 JSON 那一行之後再印：

- exit 0 或 10：`Changelog 最新：vX.Y.Z（YYYY-MM-DD，本次讀網頁確認）`（全形冒號、全形括號、全形逗號，一字不差）。
- exit 10 時，接著每條新條目印一行：`- [vX.Y.Z] <section>: <text>`。
- exit 2：只印 `Changelog 本次未能讀取`。

### A6 fixture：`routines/fixtures/changelog_sample.html`

自己寫的完整 HTML 檔（UTF-8），**剛好三個** `<article>` 區塊，頁面順序如下；閘門會直接拿這些值比對：

| 順序 | `<h2 id>` | `<time datetime>` | 條目（段名：文字） |
|---|---|---|---|
| 1 | `v2.10.0` | `2026-01-20` | `New`：`Calendar sync now runs every 5 minutes.`；`New`：`Search & filters load twice as fast. Beta`；`Fixed`：`Fixed a crash when a list was empty.` |
| 2 | `v2.9.1` | `2026-01-12` | `Improved`：`Settings page remembers the last tab.`；`Fixed`：`Fixed dates showing in the wrong order.` |
| 3 | `v2.9.0` | `2026-01-05` | `New`：`Added dark mode.` |

寫法要求（用來證明解析器不會被常見雜訊騙）：

- 第 1 區塊的 `<time>` 屬性寫成 `dateTime="2026-01-20"`，標籤內文是 `January 20, 2026`。
- 每個區塊在 `<h2>` 前有一個 `<a href="#vX.Y.Z">v<!-- -->X.Y.Z</a>`。
- 第 1 區塊 `<h2>` 後有 `<p>Also includes <!-- -->2.9.2</p>`（2.9.2 不是合格版號來源，不得被當成一版）。
- `Search & filters...` 那條在 HTML 裡寫成 `<li><span aria-hidden="true" class="dot"></span><span>Search &amp; filters load twice as fast.<span class="badge">Beta</span></span></li>`，解析後正好是表中的文字。
- `<article>` 之外有一個 `<h2 id="v9.9.9">` 的誘餌（例如頁首），不得被當成一版。

## 腳本 B：`routines/daily_file_presence.py`

### B1 參數

| 參數 | 必填 | 說明 |
|---|---|---|
| `--root DIR` | 是 | 要看的根目錄。不存在或不是目錄 → exit 2，`error` 以 `bad_root` 開頭 |
| `--date YYYY-MM-DD` | 否 | 預設＝執行當下的 JST（UTC+9）日期。格式錯或不存在的日期 → exit 2，`error` 以 `bad_date` 開頭 |
| `--pattern P` | 是，可重複，至少 1 個 | 相對 `--root` 的路徑樣板。**沒有預設值**；給幾個就查幾個，順序＝參數出現順序（第一個就是呼叫端的首選檔）。一個都沒給 → argparse 用法錯誤 exit 2 |

- 樣板只認兩個佔位：`{YYYY-MM-DD}`（例如 `2026-01-20`）、`{YYYYMMDD}`（例如 `20260120`），用字串取代展開，不用 `str.format`。分隔符一律寫 `/`，腳本再轉成作業系統路徑。
- 本檔、測試與閘門的範例樣板一律用中性名稱，例如 `a/report-{YYYY-MM-DD}.json`、`b/report_{YYYYMMDD}.md`。
- 樣板有其他佔位（含小寫 `{date}`）或括號不成對、是絕對路徑、含 `..` 段、含 `\`、或展開後是空字串 → exit 2，`error` 以 `bad_pattern` 開頭。
- JST 用固定位移 `datetime.timezone(datetime.timedelta(hours=9))`，**不用** `zoneinfo`（Windows 沒裝 tzdata 也要能跑），不讀 `TZ` 環境變數。

### B2 檢查

- 固定順序：照 `--pattern` 的順序，每個樣板只檢查**一個**路徑，就是用 `--date` 展開後的那一個。不找前一天、不找相近檔名、不列目錄。
- 「在」＝該路徑是一般檔案（`is_file()` 為真）；同名資料夾算「不在」。
- `mtime`：`os.stat(...).st_mtime` 換成 JST 的 ISO 8601，到秒，帶 `+09:00`（例如 `2026-11-17T18:15:02+09:00`）；不在時為 `null`。不管執行機器的時區設定，一律輸出 `+09:00`。

### B3 結果

JSON 鍵**剛好** `date`、`files`、`status`、`first_present`、`missing`、`error` 六個。

- `date`：用到的日期字串 `YYYY-MM-DD`（exit 2 時可為 `null`）。
- `files`：清單，元素數＝`--pattern` 個數，順序同參數；每個元素鍵剛好 `order`（從 1 起算的整數）、`path`（相對 `--root`、用 `/` 分隔的展開後路徑）、`exists`（bool）、`mtime`（字串或 `null`）。exit 2 時為 `[]`。
- `status`：全部都在 `"all"`／有在有不在 `"partial"`／全部不在 `"missing"`；exit 2 時為 `"error"`。
- `first_present`：照順序第一個在的檔的 `path`；全部不在或 exit 2 時為 `null`（呼叫端「先用首選、沒有再用備用」就看這個欄位）。
- `missing`：不在的檔的 `path` 清單，順序同 `files`；exit 2 時為 `[]`。
- `error`：正常時 `null`；exit 2 時為以 B1 代碼開頭的非空字串。
- 輸出**不得**含 `--root` 的實際路徑（避免把私人路徑帶進日報）。

### B4 exit code

| 情況 | exit |
|---|---|
| 至少一個在（`all`／`partial`） | 0 |
| 全部不在（`missing`） | 3 |
| 參數錯（B1） | 2 |

### B5 不讀內容的證據

第一個樣板對到的檔權限設成 `000`（Linux，非 root）時，腳本仍要回報 `exists=true` 且 exit 0（`stat` 不需要讀權限；若實作偷讀內容就會失敗）。

## T1 測試

- 兩個測試檔用標準庫 `unittest`；分別 `import changelog_version_check`、`import daily_file_presence`（模組層 import，靠 `PYTHONPATH=routines`）。
- fixture 路徑由測試檔自己的位置推出，不寫絕對路徑。
- **離線**：測試不得連任何網路。腳本 A 的測試只用 `--input-file`、直接呼叫解析／`main()`，或 `unittest.mock.patch("urllib.request.urlopen")`。測試在 `socket.socket.connect` 被換成「一呼叫就 raise」的情況下仍要全綠。
- 腳本 B 的測試只在 `tempfile.TemporaryDirectory()` 裡建檔，用 `os.utime` 設固定 mtime 驗輸出。
- repo 根跑 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=routines python -m unittest discover -s routines/tests` 退出 0，跑到的測試數 ≥ 16。
- 至少要有：
  1. A：fixture 對 A6 表：上一版 `v2.10.0` → exit 0、`changed=false`；`v2.9.1` → exit 10、3 條；`2.9.0`（不帶 v）→ exit 10、5 條；`v2.9.10` → exit 10（數值比較，不是字串比較）；`v3.0.0` → exit 0、`changed=false`、`version="v2.10.0"`。
  2. A：exit 2 各路：空頁、只有誘餌 `h2`、每個 `<article>` 都沒有有效日期、重複版號、`bad_previous_version`、`bad_url`（`file://`，且斷言 `urlopen` 沒被呼叫）、mock `urlopen` raise `HTTPError(404)` 與 `URLError`；每一路都斷言 `version is None` 且不等於上一版。
  3. A：mock `urlopen` 回傳 fixture bytes 時，結果與 `--input-file` 相同，且 `urlopen` 收到的 URL 就是 `--url` 給的值、timeout 等於 `--timeout`。
  4. A：`--text-line` 三種輸出（0、10、2）逐字比對 A5。
  5. B：用 `--pattern a/report-{YYYY-MM-DD}.json --pattern b/report_{YYYYMMDD}.md` 跑四種情況（兩檔都在、只有第一個、只有第二個、都不在）→ `status` 依序 `all`／`partial`／`partial`／`missing`、`first_present` 依序第一個／第一個／第二個／`null`、exit 0／0／0／3；只給一個 `--pattern` 也能跑；`--pattern` 一個都沒給 → exit 2；`mtime` 符合 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$` 且換算回去等於設定的時間戳。
  6. B：只放「前一天」的兩個檔 → `missing`、exit 3；同名資料夾 → 不在；三個 `--pattern` 時順序與 `order` 正確；`bad_pattern`（`../x`、絕對路徑、`{foo}`、`{date}`）、`bad_date`、`bad_root` → exit 2。
  7. B：跑完前後，暫存目錄下所有路徑與 mtime 完全相同（沒寫檔）。

## Definition of done（全部可機器判定）

1. `python tools/check_012.py` exit 0，最後一行 `RESULT: ALL PASS`。
2. 實作 PR head 上 `python3 tools/ci_run_gates.py` 的 `gate` job 綠：選到 `012`、`scope: PASS`、`lock: PASS`、`CI RESULT: PASS`。
3. 實作 PR diff（相對 main，三點 diff）的檔案集合 == {`routines/changelog_version_check.py`, `routines/daily_file_presence.py`, `routines/fixtures/changelog_sample.html`, `routines/tests/test_changelog_version_check.py`, `routines/tests/test_daily_file_presence.py`}。
4. T1 指令 exit 0，跑到的測試數 ≥ 16。
5. `python tools/check_010.py`、`python tools/check_011.py` 在同一棵樹上仍 exit 0。
6. 驗收只用 shell，不開瀏覽器、不連真實 changelog 網址。

## 閘門（給 Gpt小豬，本 PR 不寫）

`tools/check_012.py` 沿用 007、008、010、011 的寫法：標準庫、離線、ASCII stdout；子程序設 `PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`、自設 `PYTHONPATH=routines`；活檔只讀，突變在暫存複本；每項印 `[PASS]`／`[FAIL]`／`[BLOCKED]`，結尾 `RESULT: ALL PASS` 或 `RESULT: FAIL`。建議項目：

- **G1 形狀**：五檔存在；兩支腳本 `import` 時 stdout、stderr 皆空；`ast` 確認有 `main` 函式、import 只來自標準庫（`sys.stdlib_module_names` 或閘門內建白名單）。
- **G2 只讀（靜態）**：`ast` 掃兩支腳本，不得呼叫 `open(...)` 帶寫入模式（`w`／`a`／`x`／`+`）、`write_text`、`write_bytes`、`mkdir`、`makedirs`、`remove`、`unlink`、`rename`、`replace`、`rmdir`、`chmod`、`shutil.*`、`tempfile.*`；腳本 B 另外不得呼叫 `open`、`read_text`、`read_bytes`、`listdir`、`scandir`、`glob`、`iterdir`、`walk`、`zoneinfo`。
- **G3 A 行為**：閘門自己組參數跑 `python routines/changelog_version_check.py --input-file routines/fixtures/changelog_sample.html --previous-version ...`，逐項比對 T1 第 1 條的 exit code、JSON 五鍵與值、`new_entries` 內容（照 A6 表，閘門內建成常數，不在執行時解析 spec）；JSON 第一行是純 ASCII。
- **G4 A 讀不到**：(a) 閘門在 127.0.0.1 開一個立刻關閉的埠，`--url http://127.0.0.1:<該埠>/` → exit 2、`version` 為 null、`error` 以 `fetch_failed` 開頭；(b) `--url file:///etc/hostname` → exit 2、`bad_url`；(c) 暫存檔寫空頁、只有誘餌的頁 → exit 2、`parse_failed`；(d) 上述每一路加 `--text-line`，第二行剛好 `Changelog 本次未能讀取`。全程不連 127.0.0.1 以外的位址。
- **G5 A 文字行**：exit 0 與 10 的 `--text-line` 輸出逐字等於 A5。
- **G6 B 行為**：暫存目錄建檔、`os.utime` 設固定時間，用 `--pattern a/report-{YYYY-MM-DD}.json --pattern b/report_{YYYYMMDD}.md` 跑 T1 第 5 條的四種情況與「只有前一天的檔」→ exit 0／0／0／3／3；`files`、`status`、`first_present`、`missing` 對預期；不給 `--pattern` → exit 2；設 `TZ=UTC` 與 `TZ=America/New_York` 各跑一次，`mtime` 都是 `+09:00` 且相同；輸出不含暫存根目錄字串；權限 `000` 的第一個檔仍 `exists=true`（root 執行時印 `[BLOCKED]` 不算紅）。
- **G7 沒寫檔（動態）**：G3～G6 每次執行前後，對暫存目錄與 repo 活檔（略 `.git`、`__pycache__`）算路徑集合與 sha256，完全相同。
- **G8 測試全綠且離線**：用一個先把 `socket.socket.connect` 換成「呼叫就 raise」再跑 `unittest discover -s routines/tests` 的包裝程式執行，exit 0，`Ran N tests` 的 N ≥ 16。
- **G9 突變必須紅**：在暫存複本對腳本尾端附加包裝（不依賴實作內部寫法），每個突變都要讓 T1 指令 exit 非 0：
  - **M1 讀不到時回填上一版**：A 的 `main` 包一層，exit 2 時把輸出 `version` 改成 `--previous-version` 的值。
  - **M2 字串比版號**：A 改成以字串比較判定「較新」（`v2.9.10` 會被判成比 `v2.10.0` 新）。
  - **M3 找前一天**：B 的 `main` 包一層，第一個樣板的檔不在時改看前一天的同一個檔。
- **G10 公開 repo 衛生與回歸**：五檔符合 C4；`python tools/check_010.py`、`python tools/check_011.py` exit 0。
- **G11 不洩露私人資料夾結構**：對 `routines/` 底下所有檔與 `specs/012-routine-scripts.md`，不分大小寫搜尋閘門內建的禁字清單，一個都不得出現。禁字在閘門裡用字串拼接寫（避免閘門自己或本 spec 命中），至少包含：底線加 h、o、r、n 四字母；r、e、d、d、i、t 六字母；v、a、u、l、t 五字母；機器名與使用者帳號名（由 Clau小羊 在閘門交接時私下提供給 Gpt小豬，以拼接形式寫進閘門，不寫進本 spec）。另外確認 `daily_file_presence.py` 的 argparse 定義裡 `--pattern` 沒有 `default`。

## 範圍與 PR 形狀（CI 會怎麼判）

`tools/ci_run_gates.py` 用**整張 PR 的 diff** 判範圍。

- **PR A（本 PR，spec only）**：只新增 `specs/012-routine-scripts.md`。spec 沒有 `expected_paths` 表格列 → `discover()` 略過本檔；diff 不碰任何工單的 `expected_paths` → regression 模式跑既有全部閘門，應與 main 同為綠。lock 不動。
- **PR B（閘門＋鎖，Gpt小豬）**：把 expected_paths 移進表格、加 `tools/check_012.py`、lock 加 012（三者同一張 PR）。預期選到 012、scope／lock PASS、`check_012` 紅（尚未實作），回歸項（`check_010`、`check_011`）綠。
- **PR C（實作，Gemi小狗，PR B 合進 main 後才開）**：只新增五個檔（`routines/` 下兩支腳本、一個 fixture、兩個測試檔）。只 `git add` 這五檔並設 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 進 diff 造成 `scope: FAIL`。證據貼 PR 留言，不進 diff。

## 不做的事

- 不改 `src/`、`tests/`、`fixtures/`、`workbench/`、`.github/`、`specs/001`～`011`。
- 不改 `tools/check_001.py`～`check_011.py`、`tools/ci_run_gates.py`，不改 lock 裡既有紀錄。
- 不接任何例行、不改任何 Bot 的例行內容、不排程；接不接由各負責 Bot 之後自己決定。
- 不加 pytest 或任何 pip 依賴；腳本不寫檔；測試與閘門不連 127.0.0.1 以外的網路。
- 不在 repo 放任何私人路徑、帳號、機器名、館藏名、例行 id；文件與輸出一律用 `<ROOT>` 一類佔位。
- 不把 `gate` 設成 required（repo 設定由擁有者決定）。
