# Hello GitHub Starter

這是一個超輕量的示範專案，用來練習 Git 與 GitHub 的基本操作。

## 你可以練習的事情
- 建立 repository
- 上傳檔案（或用 Git 指令推上去）
- 做一次修改與 commit / push
- 建立分支、發出 Pull Request、合併

## 快速開始（網頁上傳）
1. 到 GitHub 建立一個新的 Repository（例如 `hello-github`），保持「Public」。
2. 把這個專案資料夾的內容上傳到新 Repository。
3. 完成後，在 repo 首頁應該能看見這份 README 與 `src/hello.py`。

## 快速開始（Git 指令）
```bash
# 1) 進到專案資料夾
cd hello-github-starter
python src/hello.py

# 2) 初始化 Git
git init
git add .
git commit -m "feat: initial commit"

# 3) 建立 main 分支（若需要）
git branch -M main

# 4) 連結到你的 GitHub 遠端（把 <user> 與 <repo> 換成你的）
git remote add origin https://github.com/<user>/<repo>.git

# 5) 推上 GitHub
git push -u origin main
```

## 做一次修改
- 打開 `src/hello.py`，把訊息改成你自己的問候語。
- `git add .` → `git commit -m "chore: update greeting"` → `git push`

## 建立分支與 PR（進階）
```bash
git checkout -b feature/readme-update
# 修改 README.md 或 src/ 檔案
git add .
git commit -m "docs: update README"
git push -u origin feature/readme-update
```
然後到 GitHub 網頁點選「Compare & pull request」，建立 PR，檢查後合併。

## CI 工單閘門

`.github/workflows/gate.yml` 的 job 名稱是 `gate`。每個 pull request，以及 push 到 `main`，都會跑 `python3 tools/ci_run_gates.py`，真的執行工單閘門。

本倉沒有 manifest，也沒有 `accept_work_order.py`。腳本從 `specs/*.md` 表格的 `expected_paths` 讀路徑（並帶上該單的 `tools/check_NNN.py`），看這次 diff 碰到哪些工單，再跑對應的 `python3 tools/check_NNN.py`。任一閘門不是退出 0，job 就失敗。diff 沒碰到任何工單路徑時，既有閘門全部當回歸跑一遍。

不改既有 `check_NNN.py`，也不把 spec 裡的 Definition of done 當指令執行。只用標準庫，不上網、不讀密鑰。

只跑被碰到的工單；完全沒碰到才全跑。因此只改 `src/agy_wrote.txt` 時不會連帶跑 003／004 裡面對 001 的回歸。

紅燈不會自動擋住合併。check 名稱是 `gate`。要擋，必須在分支保護或 ruleset 把它設成 required。這次沒有改 repository 設定。

---

祝練習順利！
