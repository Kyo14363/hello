# hello 與 kyo-work 的閘門對照

這份是給規劃讀的參考實作。hello 留在 hello。不要把這裡的 workflow、鎖檔或 005 示範搬進 kyo-work。

check 名稱是 `gate`。job 會紅，但合併不會被擋住，除非擁有者在分支保護或 ruleset 把 `gate` 設成 required。這次沒有改 repository 設定。

| 面向 | hello | kyo-work | 擋得住什麼 |
|---|---|---|---|
| 在哪跑 | 每個 pull request，以及 push 到 `main`，Actions job `gate` 跑 `python3 tools/ci_run_gates.py`，再跑對到的 `python3 tools/check_NNN.py`。diff 沒碰到任何工單就全部回歸。 | 本機完成定義是 `python tools/accept_work_order.py --manifest` 退出 0。名為 `gate` 的 CI 不跑任何 `check_NNN.py`。 | hello 的紅燈表示某支閘門真的沒過。kyo-work 綠掉的 CI 不能拿來當閘門已過。 |
| 範圍從哪來 | `specs/*.md` 表格裡的 `expected_paths`。沒有 manifest，也沒有 `outside_paths`。 | 每張工單一張 manifest，裡面有 `expected_paths` 和 `outside_paths`。 | 兩邊都把「這張單可以碰哪些檔」寫成看得到的清單。 |
| 範圍檢查 | 一旦 diff 碰到某張工單，扣掉基礎建設檔之後，每個改動檔都必須在該單的 `expected_paths` 裡，否則 job 失敗。基礎建設只有 `.github/`、`docs/`、`README.md`、`tools/ci_run_gates.py`、`tools/gate_acceptance_lock.json`。 | 本機 A1/A3 檢查實作者沒有改到範圍外。`outside_paths` 曾被放寬到整個根目錄，那項檢查就不再咬人。 | hello 擋「做某一張單，卻同時改了那張單清單以外的檔」。kyo-work 的 A1/A3 在根目錄被放進 `outside_paths` 之後，擋不住這件事。 |
| 閘門完整性 | `tools/gate_acceptance_lock.json` 記下每支已驗收 `check_NNN.py` 與該 spec 的 `expected_paths` 那一列的 sha256。CI 對這份已提交的 pin，不會用活樹重算基準。位元組或那一列有改，必須在鎖檔追加一筆 re-acceptance（非空原因 + 新哈希），舊的紀錄不能改寫。 | A5 比對包含閘門檔在內的哈希。`check_012.py` 在驗收之後被改過，基準變成當時的活樹，比對變成自己對自己。 | hello 擋「驗收之後改閘門，再讓基準跟著活樹走」。要改可以，PR 裡看得到原因和新哈希。 |
| 網路 | 標準庫、離線、不讀密鑰。checkout 拉完程式之後，閘門不再對外連線。 | 閘門會上網抓清單（SITCA）。 | hello 的結果不跟外站當天的回應一起變。 |
| 資料層測試 | 工單 005 把名冊、完整批次、列數地板過但缺代號的批次、非營業日／事件排除清單收成固定檔。完整批次要過；地板過但仍有未解釋缺口要拒；清單解釋得了的缺口可以過；清單檔不在就拒。好壞兩種結果都在 `tools/check_005.py`，CI 每次都跑。 | 夜間台股擷取只在真實夜間資料上跑：名冊要齊、列數地板至少 3000、非營業日／事件清單解釋缺口。一批 3532 列仍缺 774 個基金代號，曾被拒絕。 | hello 把「列數夠、名冊卻不齊」固定在倉庫裡，沒有夜間批次也測得到。kyo-work 那個拒絕只在真實資料上發生過。 |
| 合併擋不擋 | `gate` 失敗會讓這次檢查變紅。預設仍可合併。擁有者要把 check `gate` 設成 required，才會擋住。 | CI 的 `gate` 不跑閘門，也不是 required。 | 兩邊現在都不能靠 CI 的預設值阻止合併。hello 至少把閘門結果亮在 `gate` 上。 |

## 範圍檢查怎麼判

碰到的工單是：改動路徑落在該單 `expected_paths`（或該單的 `tools/check_NNN.py`）裡。對每一張被碰到的工單，diff 裡不屬於基礎建設的檔都必須出現在那張單自己的 `expected_paths`。有一張對不上，job 就失敗。

因此只改 `src/hello.py` 可以過：003 和 004 的清單都有這個檔。若再改只有 003 有的 `artifacts/agy-003.json`，004 也被 `src/hello.py` 碰到，而那個 artifact 不在 004 的清單裡，範圍檢查失敗。

完全沒碰到工單時不做這項檢查，既有閘門改跑回歸。所以單獨改 `tools/jev_smoke.py` 不會被範圍檢查殺掉。一旦同一張 diff 又碰到工單，那個檔就必須在被碰到的每一張單的清單裡，否則失敗。

只跑被碰到的工單。只改 `src/agy_wrote.txt` 時不會連帶跑 003／004 裡面對 001 的回歸。

## 鎖檔怎麼判

pin 是鎖檔裡寫下的 sha256，不是 CI 當下從活樹現算了一份基準再自己比對。活檔的哈希必須等於 pin。跟 base 比起來，閘門位元組或 spec 那一列有變，head 的 `acceptances` 必須在 base 的紀錄後面追加一筆，而且最後一筆的哈希就是新的 pin、`reason` 非空。改寫舊紀錄不算 re-acceptance。

鎖檔第一次落地時，pin 就是當時 main 上那些閘門的位元組。從下一次改動起，上面的追加規則才有 base 可比。CI 不會把活樹寫回鎖檔。
