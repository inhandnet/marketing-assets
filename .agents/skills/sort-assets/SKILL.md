---
name: sort-assets
description: 整理「待上传」文件夹里随手丢进来的市场素材：由 AI 判断每个文件属于哪个型号、解决方案还是品牌资料，中文还是英文、是图片 / 宣传册 / 视频，拿不准的问用户，确认后放进正确的文件夹，再交给 upload-assets（不压缩）或 compress-upload-assets（用户要求压缩时）上传。当用户说"整理素材""帮我分类""待上传里的文件""帮我放到对应文件夹""整理并上传""整理并提交""整理并压缩上传"时触发；上传 / 提交素材时「待上传」里有文件，也按本 skill 整理。
---

# sort-assets

本 skill 与 Claude Code 共用同一份完整步骤：`.claude/skills/sort-assets/SKILL.md`。
**先读取该文件，然后严格按其中的步骤执行。**

在 Codex 中使用时：
- 文中「用 Read 打开图片」= 用查看图片的功能打开图片。
- 运行 `python scripts/upload.py push` 时需要写 `.git` 并联网，默认沙盒会拦截：请向用户申请在沙盒外运行该命令，同意后再执行。其余命令在沙盒内即可运行。
