# Work order 005 - 離線資料閘示範

| Field | Content |
|------|---------|
| Status | 示範閘門。給規劃對照用，不接真实行情，也不帶回 kyo-work |
| Repo | https://github.com/Kyo14363/hello |
| expected_paths | `specs/005-offline-data-gate-demo.md`、`tools/check_005.py`、`fixtures/005/roster.csv`、`fixtures/005/batch_complete.csv`、`fixtures/005/batch_floor_but_missing.csv`、`fixtures/005/batch_gap_explained.csv`、`fixtures/005/exclusions.csv` |
| Definition of done | `python tools/check_005.py` exits 0 |

本單不改 `tools/check_001.py` 到 `tools/check_004.py`，也不改那些工單的交付檔。

## 對照的形狀

夜間資料閘要同時看三件事：名冊上的代號是否都到了、資料列是否達到地板、缺的代號是否被非營業日或事件清單解釋。列數過了地板並不表示名冊齊。曾有一批 3532 列、地板 3000，仍因缺 774 個基金代號被拒絕。那個檢查只在真實夜間批次上跑過，而且會上網取清單。

本單把同一形狀收成倉庫裡的固定檔。CI 每次跑 `python tools/check_005.py`，不上網。數字是玩具：名冊 10 個代號，列數地板 8。

## 規則

- `fixtures/005/roster.csv` 是 F01 到 F10。
- 列數地板是 8。重複列算進列數，不算成另一個代號。
- 名冊上每個代號都要出現在批次裡。沒出現的，必須在 `fixtures/005/exclusions.csv`，`kind` 只能是 `non-business-day` 或 `event`，`reason` 不能空。
- 排除清單這個檔不存在就拒絕。只有表頭的空檔仍然算檔案存在。
- `batch_complete.csv` 有 10 列且代號齊，要過。
- `batch_floor_but_missing.csv` 有 9 列（地板過）但缺 F08、F09、F10。排除清單只點名 F08 與 F09，所以 F10 仍未解釋，要拒絕。
- `batch_gap_explained.csv` 有 8 列，只缺 F08 與 F09，兩筆都在排除清單上，要過。

## 閘門

`tools/check_005.py` 用標準庫、離線、ASCII stdout。四件事都在同一次執行裡：

- **G1** 完整批次過
- **G2** 地板過、仍有未解釋缺口，必須紅
- **G3** 缺口都被排除清單解釋，過
- **G4** 排除清單路徑不存在，必須紅

活檔只讀。G4 指到一個不會建立的暫存路徑，不刪倉庫裡的 `exclusions.csv`。
