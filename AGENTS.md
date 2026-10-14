# marketing-assets

本文件供 Codex 等读取 `AGENTS.md` 的工具使用。项目说明与 Claude Code 共用，保存在 `CLAUDE.md`：
**开始任何操作前，先读取 `CLAUDE.md` 并严格遵守其中的规则。**

skill 在 `.agents/skills/`（内容指向 `.claude/skills/` 里的完整步骤）：上传素材、压缩并上传素材、整理素材。

在 Codex 中：检查、整理、写描述可在默认沙盒内完成；最后「提交并推送到 GitHub」需要写 `.git` 和联网，
沙盒会拦截，此时请向用户申请在沙盒外运行 `python scripts/upload.py push`，用户同意后再执行。
