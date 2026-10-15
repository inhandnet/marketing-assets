# 市场素材库安装说明（给 Claude Code / Codex 执行）

用户是市场部同事，不熟悉命令行。请你按下面步骤帮他完成安装：全程用简短中文说明进度，命令由你来运行；只有标注「需要用户本人」的步骤才请用户操作。每一步先检查，已经满足就跳过。

素材库位置：Windows 用 `D:\市场素材库`（没有 D 盘时用 `%USERPROFILE%\市场素材库`）；Mac 用 `~/Documents/市场素材库`。

## 1. 安装 Git、GitHub CLI、Python 3

先用 `git --version`、`gh --version`、`python --version`（Mac 用 `python3 --version`）检查，只装缺的。

- **Windows**：
  - `winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements`
  - `winget install --id GitHub.cli -e --source winget --accept-package-agreements --accept-source-agreements`
  - `winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements`
  - 安装时可能弹出「是否允许此应用对你的设备进行更改」，提醒用户点「是」。装完后当前终端可能找不到新命令：重新读取 PATH（PowerShell：`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`），或直接用完整路径（如 `C:\Program Files\GitHub CLI\gh.exe`）。
  - 注意：`python` 可能只是 Windows 应用商店的占位程序，`python --version` 能真正输出版本号才算已安装。
- **Mac**：用 Homebrew：`brew install git gh python@3.12`。
  - 没有 Homebrew 时（**需要用户本人**）：安装要输入开机密码，请用户自己打开「终端」运行 `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`，装完告诉你。
- 没有 winget、提示需要管理员密码、或安装失败：告诉用户请 IT 协助，或改用操作手册里的一键安装命令。

## 2. 登录 GitHub（需要用户本人）

先运行 `gh auth status`，已登录就跳过。

未登录时，登录要在浏览器里用**用户自己的** GitHub 账号完成，不能由你代替。请用户自己运行下面的命令（Claude Code 里可以直接输入 `! gh auth login --hostname github.com --git-protocol https --web`；Codex 或其他情况请用户打开「终端」/「PowerShell」运行）：

```
gh auth login --hostname github.com --git-protocol https --web
```

告诉用户：屏幕会显示 8 位验证码，按回车打开浏览器，登录自己的 GitHub 账号，输入验证码，点 Authorize。完成后你再运行 `gh auth status` 确认，然后运行 `gh auth setup-git`。

再检查上传权限：`gh api repos/inhandnet/marketing-assets --jq .permissions.push`。不是 `true` 时提醒用户把 GitHub 用户名发给管理员开通（不影响继续安装）。

## 3. 拉取素材库

- 素材库位置已有 `.git`：运行 `git -C <位置> pull`。
- 位置已存在且不是空文件夹：停下来问用户怎么处理，不要删除或覆盖。
- 否则：`gh repo clone inhandnet/marketing-assets <位置>`

## 4. 安装 Python 依赖

- Windows：`python -m pip install --user pillow pyyaml`
- Mac（Homebrew 的 Python）：`python3 -m pip install --user --break-system-packages pillow pyyaml`

下载慢或失败时加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 重试。

## 5. 设置提交署名

用 GitHub 账号和 GitHub 提供的匿名邮箱（不要用个人邮箱），只设在素材库里：

```
git -C <位置> config user.name  "$(gh api user --jq .login)"
git -C <位置> config user.email "<id>+<login>@users.noreply.github.com"
```

`<id>` 用 `gh api user --jq .id` 获取，`<login>` 用 `gh api user --jq .login`。Mac 上另外运行 `git -C <位置> config core.precomposeunicode true`。

## 6. 检查并告诉用户以后怎么用

在素材库位置运行 `python scripts/upload.py doctor`（Mac 用 `python3`），应当全部 ✓。有 ✗ 就按提示处理。

最后告诉用户：

- 素材库位置在哪里。
- 以后每次上传：在 Claude Code 或 Codex 里**打开素材库这个文件夹**（不是现在这个文件夹），说「上传素材」。Claude Code：在素材库文件夹里打开终端，输入 `claude`；Codex：把素材库文件夹作为项目打开。
- 操作方法见《市场部操作手册》。
