---
name: compress-upload-assets
description: 压缩图片并上传市场素材到 GitHub；也负责把仓库里所有图片整体压缩一次。只在用户明确要求压缩时使用：用户说"压缩并上传素材""压缩上传""压缩后上传""整体压缩""把仓库图片都压缩一下""空间不够了压缩一下"时触发。用户只说"上传素材"时不要用本 skill（用 upload-assets，不压缩）。
---

# compress-upload-assets

本 skill 与 Claude Code 共用同一份完整步骤：`.claude/skills/compress-upload-assets/SKILL.md`。
**先读取该文件，然后严格按其中的步骤执行。**

在 Codex 中使用时：
- 文中「用 Read 打开图片」= 用查看图片的功能打开图片。
- 运行 `python scripts/upload.py push` 时需要写 `.git` 并联网，默认沙盒会拦截：请向用户申请在沙盒外运行该命令，同意后再执行。其余命令在沙盒内即可运行。
