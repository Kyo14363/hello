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

---

祝練習順利！
