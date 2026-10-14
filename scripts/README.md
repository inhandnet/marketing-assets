# 维护说明（scripts 与自动化）

给仓库维护人员看的。市场部的操作方法在内部的《市场部操作手册》里，不在仓库中。

## 脚本

| 脚本 | 作用 | 谁来运行 |
| --- | --- | --- |
| `build.py` | 统一型号 / 方案文件夹名（合并重复写法）、规范文件名、生成缩略图、`catalog.json`、`llms.txt`、画廊、检查报告。`--compress` 时把图片压到长边 2000 px、转 JPG（透明图 PNG），`brand/logo/` 除外 | CI（每次推送、每小时），上传工具 |
| `sync_releases.py` | 为每个型号 / 方案文件夹和品牌资料建 Release，视频附件名改为纯英文规范名（中文原名存为附件显示名），生成 / 清理 `videos/*.yml` | CI，上传工具 |
| `sync_categories.py` | 从中英文官网 WordPress 接口生成 `categories.yml`（品类、系列、型号、解决方案；芯片厂商层级不作为系列） | CI（每周一） |
| `upload.py` | 本地上传工具：`doctor` / `check` / `push [--compress | --compress-all]` / `place`。两个 Claude Code skill 都调用它 | 市场部（经 Claude Code） |

本地运行：`pip install pillow pyyaml`，然后 `python scripts/build.py --dry-run` 预览。

## GitHub Actions

| 流程 | 触发 | 说明 |
| --- | --- | --- |
| `build.yml` | 推送到 main（`zh/`、`en/`、`categories.yml`、`scripts/`）、每小时、手动 | 视频同步 → 整理 → 提交；推送冲突时取最新 main 重新生成，最多重试 3 次；报告有变化且有问题时开 issue |
| `sync-categories.yml` | 每周一 09:00（北京时间）、手动 | 对照表有变化时重新生成清单并提交 |

不使用 `release` 事件触发：它会用标签所在旧提交里的 workflow 运行。

## Claude Code skill（`.claude/skills/`）

| skill | 触发 |
| --- | --- |
| `upload-assets` | 「上传素材」（不压缩） |
| `compress-upload-assets` | 「压缩并上传素材」「整体压缩」 |
| `sort-assets` | 「整理素材」「整理并上传」：AI 判断 `待上传/` 里文件的归属和语言 |

## 约定

- 本地提交只包含 `zh/`、`en/` 下的素材；`catalog.json`、`llms.txt`、`_generated/` 只由 CI 生成，避免冲突
- 所有生成文件统一 LF 换行（`.gitattributes`），本地与 CI 输出逐字节一致
- `待上传/`、`.已上传视频/` 只在本地，由 `upload.py` 自动创建，不进仓库
- 视频、设计源文件、3D 文件、压缩包、密钥不进仓库（`.gitignore` + `build.py` 双重检查）；`brand/logo/` 下的 AI / EPS 矢量 Logo 例外

## 已知限制与后续计划

- **Release 附件名不能用中文**：GitHub 会把文件名中的非字母数字字符替换成 `.`（[官方文档](https://docs.github.com/en/rest/releases/assets)：*"GitHub renames asset filenames that have special characters, non-alphanumeric characters…"*，已实测）。目前附件名用「英文 + 编号」，中文原名存为附件 label（Release 页面显示中文）和 `videos/*.yml` 的 title。
- **后续**：做国内云存储 / CDN 镜像时，视频按中文原名（label）另存一份，供国内下载；`build.py` 已预留 `CN_BASE_URL`（`catalog.json` 的 `url_cn` 字段）。

## Codex 支持

- Codex 从 `.agents/skills/` 读 skill、从 `AGENTS.md` 读项目说明。`.agents/skills/*/SKILL.md` 由 `build.py` 按 `.claude/skills/` 自动生成（名字、触发描述一致，正文指向 Claude 的完整步骤），**不要手改**；`AGENTS.md` 指向 `CLAUDE.md`。
- Codex 默认沙盒中 `.git` 只读，最后的提交推送需要用户授权在沙盒外运行；沙盒里 git 访问 Windows 证书 / 凭据管理器失败时，`upload.py` 会自动改用 OpenSSL + gh 令牌重试。

## Release 标签注意

- Release 事件会用**标签所指提交**里的 workflow 运行。早期标签曾指向仍带 `release:` 触发的旧提交，导致旧脚本反复给视频加前缀；2026-10-14 已把这些标签全部移到新提交。以后如果要改动 build.yml 的触发方式，记得检查已有标签指向的提交。

## 发布与网页画廊

- 仓库已公开；素材画廊由 GitHub Pages 发布（main 分支根目录）：`https://inhandnet.github.io/marketing-assets/_generated/gallery/zh.html`（英文 `en.html`）
- 根目录的 `.nojekyll` 不能删：Pages 默认用 Jekyll，会忽略以 `_` 开头的 `_generated/`
