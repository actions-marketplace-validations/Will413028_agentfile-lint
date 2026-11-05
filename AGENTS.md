# agentfile-lint

指令檔（AGENTS.md／CLAUDE.md）的檢查器：規則寫在一份 TOML，執行器只用 Python 標準庫（加一份內嵌的 PyYAML），本機 hook 與 CI 呼叫同一支。

- 本 repo 會公開：追蹤的檔案、commit 與 issue 不寫任何使用者 repo 的名稱或內部細節；設計只寫通用的部分。
- 只用 Python 標準庫（>= 3.11，`tomllib`）；執行器不得新增第三方依賴（`pyproject.toml` 的 `dependencies` 保持空）。唯一的外來程式是 `agentfile_lint/_yaml/`：PyYAML 6.0.3 純 Python 部分原樣內嵌，不改程式碼，來源與比對指令見它的 `PROVENANCE`，只由 `frontmatter.py` 以 `SafeLoader` 使用（`docs/adr/0007`）；升級它或內嵌其他第三方程式同樣要先列版本、等同意。開發與 CI 用的工具（含 Action）也不自行新增或升級：先列出套件與版本，確認它真的存在、發布滿兩週，等同意。
- 開發與驗證：`make check`（等同 `python3 -m unittest discover -s tests`；Python 低於 3.11 會明確失敗，可用 `make check PYTHON=python3.12`）。
- 對自己跑檢查：`python3 -m agentfile_lint`（預設只掃 git 追蹤的檔案；`--no-git` 改為走訪目前目錄）。
- 子命令：`vendor`、`check-pins`（各引用處釘同一個完整 SHA；experimental，不在相容性契約內）、`config --format json`（有效設定的 JSON）。
- 新規則一律以 `warn` 進入預設 preset，升 `error` 要在 CHANGELOG 的 `Graduated` 列出（`tests/test_versioning.py` 檢查）；流程見 `docs/versioning.md`。
- 規則是資料（`agentfile_lint/presets/*.toml`：`default` 只放客觀檢查、`strict` 加啟發式規則，見 `docs/adr/0003`；與 repo 設定檔），行為差異不寫成程式裡的 repo 專屬分支；未知設定鍵一律失敗。
- 輸出格式（見 `docs/design.md` 的 Output and exit codes）、規則代號、設定鍵、退出碼（0／1／2）與 `vendor`／`verify.py` 的行為是對外契約，改動要同步更新斷言它的測試；1.0 前輸出格式、規則代號、設定鍵的改動是 minor，列在 CHANGELOG 的 `Changed (breaking)`，退出碼只在 major 改（`docs/versioning.md`、`docs/adr/0004`）。
- `tests/fixtures/legacy-oracle/` 是舊檢查器的快照，只供比對，不維護、不修改。
- 模組依賴方向：`rules/` 只引用核心模組（`context`、`discover`、`errors`、`finding`、`frontmatter`、`rules._json`、`rules._text`），不引用 `cli`、`config`、`vendor`、`check_pins`；整個套件不得有循環引用（`tests/test_architecture.py` 檢查）。
- 分支模型（branch model）：日常改動在 `dev`（可直接推）；`main` 只放已發布的程式，只經 `dev` → `main` 的 PR 改動，CI 全綠後用 merge commit 合併（不 squash），發版流程見 `docs/versioning.md`。漏洞修補期限與回報管道見 `SECURITY.md`。
- 設計見 `docs/design.md`，決定見 `docs/adr/`。
