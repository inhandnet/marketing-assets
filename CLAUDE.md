# marketing-assets

映翰通公开市场素材库。日常使用者是市场部同事（不熟悉 Git / GitHub），请始终用简短的中文交流，不要让他们自己输入命令。

- 上传素材（默认不压缩，保留原图）：使用 skill `upload-assets`
- 用户明确说「压缩并上传素材」或「整体压缩」时：使用 skill `compress-upload-assets`
- 整理「待上传」文件夹里的散乱文件：使用 skill `sort-assets`
- 所有文件操作都通过 `python scripts/upload.py`（doctor / check / push / place）完成
- 不要直接运行 git 命令，不要修改 `scripts/`、`.github/`、`categories.yml`、`catalog.json`、`llms.txt`、`_generated/`（这些由程序和 GitHub 自动维护）

目录结构见 `README_CN.md`；文件放置规则见各 skill；脚本和自动化说明见 `scripts/README.md`。
