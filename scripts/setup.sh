#!/bin/bash
# 市场素材库一键安装（苹果电脑 macOS；每台电脑运行一次，重复运行也没问题：已装好的会跳过）
# 用法：打开「终端」（启动台 → 其他 → 终端），粘贴下面一行回车：
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/inhandnet/marketing-assets/main/scripts/setup.sh)"
# （不要用 curl ... | bash：那样脚本占用了输入，输入密码、登录 GitHub 的步骤没法交互）
# 会做：安装 Homebrew → Git / GitHub CLI / Python → Claude Code → 浏览器登录 GitHub → 拉取素材库
#       → 安装 Python 依赖 → 设置提交署名 → 桌面建「市场素材库」启动图标 → 环境检查
# 可选环境变量：MA_DIR 素材库位置（默认 ~/Documents/市场素材库）；MA_NO_SHORTCUT=1 不建桌面图标
# 注意：macOS 自带 bash 3.2，不要用 bash 4 以上的语法

REPO="inhandnet/marketing-assets"
DIR="${MA_DIR:-$HOME/Documents/市场素材库}"
PROFILE="$HOME/.zprofile"   # macOS 默认 zsh；登录时读取，桌面图标也会读取

say() { printf '%s\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() {
  printf '\n  \033[31m✗\033[0m %s\n' "$*"
  say "  安装未完成。处理后重新运行同一行命令即可，已完成的步骤会自动跳过。"
  exit 1
}
has() { command -v "$1" >/dev/null 2>&1; }
# 把一行配置写进 ~/.zprofile（已有就不重复写），并在当前脚本里立即生效
persist() {
  touch "$PROFILE"
  grep -qxF "$1" "$PROFILE" || printf '%s\n' "$1" >> "$PROFILE"
  eval "$1"
}

[ "$(uname)" = "Darwin" ] || fail "这个脚本只用于苹果电脑；Windows 请用 setup.ps1（见操作手册第一节）"

say ""
say "━━ 市场素材库一键安装（Mac）━━"
say ""

# 1. 软件
say "1/6 安装软件"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
if ! has brew; then
  # 连不上 Homebrew 官方下载时，改用清华镜像下载软件包
  if ! curl -fsS -m 8 -o /dev/null https://formulae.brew.sh; then
    export HOMEBREW_API_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/brew.git"
    warn "官方源连接较慢，改用清华镜像"
  fi
  say "  … 正在安装 Homebrew（软件安装工具）。提示 Password 时输入这台 Mac 的开机密码（输入时不显示），回车"
  say "    如果弹出「安装命令行开发者工具」，点「安装」并等它完成"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && persist "eval \"\$($b shellenv)\"" && break
  done
fi
has brew || fail "Homebrew 安装失败。请检查网络后重试，或请 IT 协助安装 https://brew.sh"
ok "Homebrew"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do  # 已装过 Homebrew 但没写进配置的，也补上
  [ -x "$b" ] && persist "eval \"\$($b shellenv)\"" && break
done

for pkg in git gh python@3.12; do
  if ! brew list "$pkg" >/dev/null 2>&1; then
    say "  … 正在安装 $pkg"
    brew install -q "$pkg" || fail "$pkg 安装失败，请检查网络后重新运行"
  fi
done
# 让 python / pip 命令指向 Homebrew 的 Python（素材库的工具用 python 命令运行）
persist "export PATH=\"$(brew --prefix python@3.12)/libexec/bin:\$PATH\""
has git && ok "Git" || fail "Git 不可用"
has gh && ok "GitHub CLI" || fail "GitHub CLI 不可用"
python -c "import sys; assert sys.version_info >= (3, 9)" 2>/dev/null && ok "Python" || fail "Python 不可用"

if ! has claude; then
  say "  … 正在安装 Claude Code"
  curl -fsSL https://claude.ai/install.sh | bash >/dev/null 2>&1
fi
[ -x "$HOME/.local/bin/claude" ] && persist 'export PATH="$HOME/.local/bin:$PATH"'
if has claude; then ok "Claude Code"; else warn "Claude Code 未能自动安装（可能是网络原因），请 IT 按公司方式安装；其余步骤继续"; fi

# 2. 登录 GitHub（必须本人账号）
say ""
say "2/6 登录 GitHub"
if ! gh auth status >/dev/null 2>&1; then
  say "  接下来会显示一个 8 位验证码，按回车打开浏览器：在浏览器里登录【你自己的】GitHub 账号，输入验证码，点 Authorize。"
  gh auth login --hostname github.com --git-protocol https --web </dev/tty
  gh auth status >/dev/null 2>&1 || fail "GitHub 没有登录成功"
fi
gh auth setup-git >/dev/null 2>&1
LOGIN="$(gh api user --jq .login)"
ok "已登录：$LOGIN"
if [ "$(gh api "repos/$REPO" --jq .permissions.push 2>/dev/null)" != "true" ]; then
  warn "账号 $LOGIN 还没有素材库的上传权限：请把用户名发给管理员开通（不影响继续安装）"
fi

# 3. 拉取素材库
say ""
say "3/6 拉取素材库到 $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q && ok "素材库已存在，已更新到最新" || warn "更新失败（不影响使用，上传时会自动更新）"
else
  if [ -d "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    fail "$DIR 已存在且不是空文件夹。请改名或移走后重新运行"
  fi
  mkdir -p "$(dirname "$DIR")"
  gh repo clone "$REPO" "$DIR" || fail "拉取失败，请检查网络后重新运行"
  ok "已拉取"
fi

# 4. Python 依赖（Homebrew 的 Python 默认不让装到系统里，用 --user --break-system-packages 装到个人目录；官方源不通时换国内镜像）
say ""
say "4/6 安装 Python 依赖"
PIP="python -m pip install -q --user --break-system-packages pillow pyyaml"
$PIP 2>/dev/null || $PIP -i https://pypi.tuna.tsinghua.edu.cn/simple || fail "Python 依赖安装失败，请检查网络后重新运行"
ok "pillow、pyyaml"

# 5. 提交署名：用 GitHub 账号（不暴露个人邮箱）
say ""
say "5/6 设置提交署名"
ID="$(gh api user --jq .id)"
git -C "$DIR" config user.name "$LOGIN"
git -C "$DIR" config user.email "$ID+$LOGIN@users.noreply.github.com"
git -C "$DIR" config core.precomposeunicode true   # 中文文件名与 Windows 同事保持一致
ok "$LOGIN"

# 6. 桌面启动图标 + 环境检查
say ""
say "6/6 收尾"
if [ -z "$MA_NO_SHORTCUT" ]; then
  LAUNCHER="$HOME/Desktop/市场素材库.command"
  cat > "$LAUNCHER" <<EOF
#!/bin/zsh -l
cd "$DIR" && claude
EOF
  chmod +x "$LAUNCHER"
  ok "桌面已建「市场素材库」图标：双击即在素材库里打开 Claude"
fi
(cd "$DIR" && python scripts/upload.py doctor)

say ""
say "━━ 安装完成 ━━"
say "素材库位置：$DIR"
say "以后使用：双击桌面「市场素材库」，对 Claude 说「上传素材」。"
say "第一次打开 Claude 时：按提示登录 Claude，问是否信任这个文件夹选 Yes。"
