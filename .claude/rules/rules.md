---
description: Lint rule definitions and presets
paths:
  - "agentfile_lint/rules/**"
  - "agentfile_lint/presets/*.toml"
---

# Rules

- 一個規則代號只做一種檢查、一個等級（`docs/adr/0005`）；新的檢查另開代號，不掛在既有代號下。
- 為有公開規格的檔案寫規則前，先列出實際讀它的程式並逐一實測行為；規格與讀者不一致時，以讀者的行為為準。
- 判斷 Claude Code 怎麼處理壞掉的設定或 `.mcp.json` 時，在暫存 git repo 用 `claude doctor`／`claude mcp list` 實測並記下版本，不照文件推論。
