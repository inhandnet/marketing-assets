---
name: upload-assets
description: 上传市场素材到 GitHub（不压缩图片，保留原图）。市场部已经把图片、宣传册、视频放进 zh/ 或 en/ 下对应型号的 images / brochures / videos 文件夹后使用：检查、规范文件名、视频传到 Release、推送到 GitHub，并逐步说明过程和注意事项。当用户说"上传素材""提交素材""上传""提交""推到 GitHub""同步素材""更新素材""发布素材""检查一下素材""传上去""交素材"等意思相近的话时触发；用户说"补全素材描述""补描述"时也用本 skill（见文末「补全素材描述」）。用户说"压缩并上传""压缩上传""整体压缩"时不要用本 skill，改用 compress-upload-assets。文件还在「待上传」文件夹没归类时，先用 sort-assets。
---

# upload-assets

本 skill 与 Claude Code 共用同一份完整步骤：`.claude/skills/upload-assets/SKILL.md`。
**先读取该文件，然后严格按其中的步骤执行。**

在 Codex 中使用时：
- 文中「用 Read 打开图片」= 用查看图片的功能打开图片。
- 运行 `python scripts/upload.py push` 时需要写 `.git` 并联网，默认沙盒会拦截：请向用户申请在沙盒外运行该命令，同意后再执行。其余命令在沙盒内即可运行。
