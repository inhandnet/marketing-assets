# 市场素材库一键安装（每台电脑运行一次，重复运行也没问题：已装好的会跳过）
# 用法：开始菜单搜索「PowerShell」打开，粘贴下面一行回车：
#   irm https://raw.githubusercontent.com/inhandnet/marketing-assets/main/scripts/setup.ps1 | iex
# 会做：安装 Git / GitHub CLI / Python / Claude Code → 浏览器登录 GitHub → 拉取素材库 → 安装 Python 依赖
#       → 设置提交署名 → 桌面建「市场素材库」快捷方式 → 环境检查
# 可选环境变量：MA_DIR 素材库位置（默认 D:\市场素材库，没有 D 盘时放在用户目录）；MA_NO_SHORTCUT=1 不建快捷方式
# 注意：本文件不要带 BOM（irm | iex 会把 BOM 当成命令）

# 不用 Stop：Windows PowerShell 5.1 会把外部程序（pip、gh）写到 stderr 的提示当成错误中断；每一步都有显式检查
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Repo = 'inhandnet/marketing-assets'
$Dir = if ($env:MA_DIR) { $env:MA_DIR } elseif (Test-Path 'D:\') { 'D:\市场素材库' } else { Join-Path $HOME '市场素材库' }

function Say($t) { Write-Host $t }
function Ok($t) { Write-Host "  ✓ $t" -ForegroundColor Green }
function Fail($t) { Write-Host "`n  ✗ $t" -ForegroundColor Red; Write-Host '  安装未完成。处理后重新运行同一行命令即可，已完成的步骤会自动跳过。'; throw 'setup-stopped' }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Has-Python {
    # Windows 自带的 python 可能只是「应用商店」占位，要真能运行才算
    try { & python -c "import sys; assert sys.version_info >= (3, 9)" 2>$null; return $LASTEXITCODE -eq 0 } catch { return $false }
}
function Winget-Install($id, $name) {
    if (-not (Has 'winget')) { Fail "这台电脑没有 winget，无法自动安装 $name。请 IT 手动安装后再运行本命令" }
    Say "  … 正在安装 $name（可能弹出「是否允许更改」，请点「是」）"
    & winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements --silent | Out-Host
    Refresh-Path
}

try {
    Say "`n━━ 市场素材库一键安装 ━━`n"

    # 1. 软件
    Say '1/6 安装软件'
    if (-not (Has 'git')) { Winget-Install 'Git.Git' 'Git' }
    if (Has 'git') { Ok 'Git' } else { Fail 'Git 安装失败，请 IT 协助安装 https://git-scm.com/download/win' }
    if (-not (Has 'gh')) { Winget-Install 'GitHub.cli' 'GitHub CLI' }
    if (Has 'gh') { Ok 'GitHub CLI' } else { Fail 'GitHub CLI 安装失败，请 IT 协助安装 https://cli.github.com/' }
    if (-not (Has-Python)) { Winget-Install 'Python.Python.3.12' 'Python' }
    if (Has-Python) { Ok 'Python' } else { Fail 'Python 安装失败，请 IT 协助安装 https://www.python.org/downloads/（勾选 Add Python to PATH）' }
    if (-not (Has 'claude')) {
        Say '  … 正在安装 Claude Code'
        try { Invoke-RestMethod 'https://claude.ai/install.ps1' | Invoke-Expression } catch { }
        Refresh-Path
        $env:Path += ';' + (Join-Path $HOME '.local\bin')
    }
    if (Has 'claude') { Ok 'Claude Code' } else { Say '  ! Claude Code 未能自动安装（可能是网络原因），请 IT 按公司方式安装；其余步骤继续' }

    # 2. 登录 GitHub（必须本人账号）
    Say "`n2/6 登录 GitHub"
    & gh auth status *> $null
    if ($LASTEXITCODE -ne 0) {
        Say '  接下来会显示一个 8 位验证码并打开浏览器：在浏览器里登录【你自己的】GitHub 账号，输入验证码，点 Authorize。'
        & gh auth login --hostname github.com --git-protocol https --web
        & gh auth status *> $null
        if ($LASTEXITCODE -ne 0) { Fail 'GitHub 没有登录成功' }
    }
    & gh auth setup-git *> $null
    $login = (& gh api user --jq .login).Trim()
    Ok "已登录：$login"
    $push = (& gh api "repos/$Repo" --jq .permissions.push 2>$null)
    if ("$push".Trim() -ne 'true') { Say "  ! 账号 $login 还没有素材库的上传权限：请把用户名发给管理员开通（不影响继续安装）" }

    # 3. 拉取素材库
    Say "`n3/6 拉取素材库到 $Dir"
    if (Test-Path (Join-Path $Dir '.git')) {
        & git -C $Dir pull -q
        Ok '素材库已存在，已更新到最新'
    } else {
        if ((Test-Path $Dir) -and (Get-ChildItem -LiteralPath $Dir -Force | Select-Object -First 1)) {
            Fail "$Dir 已存在且不是空文件夹。请改名或移走后重新运行"
        }
        & gh repo clone $Repo $Dir
        if ($LASTEXITCODE -ne 0) { Fail '拉取失败，请检查网络后重新运行' }
        Ok '已拉取'
    }

    # 4. Python 依赖（官方源不通时换国内镜像）
    Say "`n4/6 安装 Python 依赖"
    & python -m pip install -q --user pillow pyyaml 2>$null
    if ($LASTEXITCODE -ne 0) { & python -m pip install -q --user pillow pyyaml -i https://pypi.tuna.tsinghua.edu.cn/simple }
    if ($LASTEXITCODE -ne 0) { Fail 'Python 依赖安装失败，请检查网络后重新运行' }
    Ok 'pillow、pyyaml'

    # 5. 提交署名：用 GitHub 账号（不暴露个人邮箱）
    Say "`n5/6 设置提交署名"
    $id = (& gh api user --jq .id).Trim()
    & git -C $Dir config user.name $login
    & git -C $Dir config user.email "$id+$login@users.noreply.github.com"
    Ok "$login"

    # 6. 桌面快捷方式 + 环境检查
    Say "`n6/6 收尾"
    if (-not $env:MA_NO_SHORTCUT) {
        $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '市场素材库.lnk'
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
        $s.TargetPath = (Get-Command powershell.exe).Source
        $s.Arguments = "-NoExit -Command `"Set-Location -LiteralPath '$Dir'; claude`""
        $s.WorkingDirectory = $Dir
        $s.Save()
        Ok '桌面已建「市场素材库」快捷方式：双击即在素材库里打开 Claude'
    }
    Push-Location $Dir
    try { & python scripts/upload.py doctor } finally { Pop-Location }

    Say "`n━━ 安装完成 ━━"
    Say "素材库位置：$Dir"
    Say '以后使用：双击桌面「市场素材库」，对 Claude 说「上传素材」。'
    Say '第一次打开 Claude 时：按提示登录 Claude，问是否信任这个文件夹选 Yes。'
} catch {
    if ("$_" -ne 'setup-stopped') { Write-Host "`n  ✗ 出错：$_" -ForegroundColor Red; Write-Host '  请截图发给管理员。' }
}
