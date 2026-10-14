#!/usr/bin/env python3
"""市场部本地上传工具（两个 Claude Code skill 共用的底层脚本，也可直接运行）。

    python scripts/upload.py doctor                 # 检查电脑环境：git、gh 登录、Python 依赖
    python scripts/upload.py check                  # 检查待上传内容，预览自动整理结果，不改任何文件
    python scripts/upload.py push                   # 正式上传（默认不压缩，图片保留原样，只规范文件名）
    python scripts/upload.py push --compress        # 压缩本次新上传的图片后上传（长边 ≤2000px，转 JPG / 透明图 PNG）
    python scripts/upload.py push --compress-all    # 整体压缩仓库里所有图片并上传
    （check 同样支持 --compress / --compress-all，用于预览）
    python scripts/upload.py place 文件... --lang zh --model IR315 [--type images]
                                                    # 把「待上传」里的文件放到正确的文件夹（skill 2 用）

本地文件夹约定（与仓库一致）：
    zh|en/products/<型号>/images/      图片
    zh|en/products/<型号>/brochures/   宣传册、彩页规格书
    zh|en/products/<型号>/videos/      视频（mp4 等不进 Git，push 时自动传到 Release <型号>-zh|en）
    待上传/                             随手丢文件的地方，由 skill 2 判断型号和语言后 place
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import (  # noqa: E402
    BLOCKED_EXT, IMAGE_EXT, LANGS, MAX_BYTES, MAX_EDGE, ROOT, compress_image, compressed_ext, load_categories,
    model_key, video_stem, locate, release_tag, release_title, load_solutions, BRAND_TYPES, LOGO_VECTOR_EXT,
    canonicalize_folders, collect, has_alpha, read_descs, rename_desc, write_descs,
)
import build  # noqa: E402  （读取 build.missing_desc）
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

INBOX = ROOT / "待上传"
UPLOADED = ROOT / ".已上传视频"          # 传到 Release 后的视频移到这里留底（不进 Git）
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm", ".mpg", ".mpeg"}
DOC_EXT = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".key"}
RELEASE_LIMIT = 2 * 1024 ** 3 - 1
GENERATED = ["catalog.json", "llms.txt", "_generated"]  # 由 GitHub 端生成，本地不提交


def say(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd: list[str], check: bool = True, capture: bool = True, env: dict | None = None) -> str:
    res = subprocess.run(
        cmd, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=capture, env={**os.environ, **(env or {})},
    )
    if check and res.returncode != 0:
        raise SystemExit(f"\n✗ 命令失败：{' '.join(cmd)}\n{(res.stderr or res.stdout or '').strip()}")
    return (res.stdout or "").strip()


MODE_TEXT = {None: "不压缩，保留原图", "new": "压缩本次新上传的图片", "all": "整体压缩仓库里所有图片"}


def images_of(paths: list[Path]) -> list[Path]:
    """需要（可以）压缩的图片：brand/logo/ 下的 Logo 保持高清，不压缩"""
    return [p for p in paths if p.suffix.lower() in IMAGE_EXT and p.exists()
            and p.relative_to(ROOT).parts[1:3] != ("brand", "logo")]


def compress_files(paths: list[Path], dry_run: bool) -> list[str]:
    """长边压到 2000px，转 JPG（有透明背景的转 PNG）；已是合适尺寸的 JPG / 透明 PNG 跳过。返回说明文字。"""
    lines = []
    for p in paths:
        with Image.open(p) as im:
            big = max(im.size) > MAX_EDGE
        ext = p.suffix.lower()
        new_ext = compressed_ext(p)
        if new_ext == ".jpg" and ext == ".jpeg":
            new_ext = ext
        if new_ext == ext and not big:
            continue  # 已经是合适的格式和尺寸
        dst = p.with_suffix(new_ext)
        if dst != p and dst.exists():
            lines.append(f"! {p.name}：同名文件 {dst.name} 已存在，未压缩")
            continue
        before = p.stat().st_size
        fmt = "PNG（有透明背景）" if new_ext == ".png" else "JPG"
        if not dry_run:
            compress_image(p, dst)
            if dst != p:
                p.unlink()
                rename_desc(p.parent, p.name, dst.name)
            lines.append(f"{p.name} → {dst.name}（{mb(before)} → {mb(dst.stat().st_size)}）")
        else:
            lines.append(f"{p.name}（{mb(before)}）→ {fmt}，长边 ≤ {MAX_EDGE}px")
    return lines


def build_report(out: str) -> tuple[list[str], list[str]]:
    """从 build.py 的输出里取出 (自动整理项, 提醒项)"""
    def items(section: str) -> list[str]:
        return [ln for ln in section.strip().splitlines() if ln.startswith("- ") and ln != "- 无"]
    after = out.split("## 自动整理", 1)[-1]
    changes, _, rest = after.partition("## 需要人工处理")
    return items(changes), items(rest.split("共 ", 1)[0])


def git_net(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """需要联网的 git 命令（pull / push）。先按正常方式执行；失败时（如 Codex 等工具的沙盒里
    Windows 证书 / 凭据管理器不可用）改用 OpenSSL + gh 登录令牌认证再试一次。
    令牌只通过环境变量传给 git，不出现在命令行参数里。"""
    def go(env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    res = go()
    if res.returncode != 0 and re.search(r"SEC_E_|schannel|Authentication failed|could not read Username|"
                                         r"terminal prompts disabled", res.stderr, re.I):
        token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            res = go({
                "GIT_CONFIG_COUNT": "3",
                "GIT_CONFIG_KEY_0": "http.sslBackend", "GIT_CONFIG_VALUE_0": "openssl",
                "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": "",
                "GIT_CONFIG_KEY_2": "http.https://github.com/.extraHeader",
                "GIT_CONFIG_VALUE_2": f"Authorization: Basic {basic}",
            })
    if check and res.returncode != 0:
        raise SystemExit(f"\n✗ 命令失败：git {' '.join(args)}\n{(res.stderr or res.stdout).strip()}")
    return res


def access_links(repo: str, staged: list[str]) -> list[str]:
    """本次上传的素材 → 查看页面和下载链接；视频给 Release 页面和视频下载链接"""
    base = f"https://github.com/{repo}"
    out = []
    for rel in staged:
        p = ROOT / rel
        if not p.exists() or p.name == "descriptions.yml":
            continue
        if p.suffix.lower() == ".yml" and "videos" in p.parts:
            meta = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            dl = meta.get("download_global")
            if not dl:
                continue
            tag = dl.split("/releases/download/", 1)[-1].split("/", 1)[0]
            out.append(f"  · 视频「{meta.get('title') or p.stem}」\n"
                       f"      查看：{base}/releases/tag/{tag}\n      下载：{dl}")
            continue
        q = quote(rel)
        out.append(f"  · {p.name}\n      查看：{base}/blob/main/{q}\n      下载：{base}/raw/main/{q}")
    return out


def mb(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


# ---------- 环境检查 ----------

def doctor(quiet: bool = False) -> bool:
    ok = True
    checks = []
    for name, cmd in (("git", ["git", "--version"]), ("gh（GitHub 命令行）", ["gh", "--version"])):
        try:
            run(cmd)
            checks.append((True, f"{name} 已安装"))
        except (FileNotFoundError, SystemExit):
            checks.append((False, f"{name} 未安装，请联系 IT 安装"))
            ok = False
    if ok:
        res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        if res.returncode == 0:
            checks.append((True, "GitHub 已登录"))
        else:
            checks.append((False, "GitHub 未登录：在终端运行 gh auth login，按提示用浏览器登录"))
            ok = False
        remote = run(["git", "remote", "get-url", "origin"], check=False)
        if "marketing-assets" in remote:
            checks.append((True, f"仓库：{remote}"))
        else:
            checks.append((False, "当前文件夹不是 marketing-assets 仓库"))
            ok = False
    try:
        import PIL, yaml  # noqa: F401,E401
        checks.append((True, "Python 依赖（pillow、pyyaml）已安装"))
    except ImportError:
        checks.append((False, "缺少 Python 依赖：运行 pip install pillow pyyaml"))
        ok = False
    if not quiet or not ok:
        say("环境检查：")
        for good, text in checks:
            say(f"  {'✓' if good else '✗'} {text}")
    return ok


# ---------- 待上传内容 ----------

def pending() -> dict[str, list[Path]]:
    """返回 {'files': 图片/宣传册等（git 未提交的）, 'videos': 本地视频, 'blocked': 不该放的}"""
    out = run(["git", "-c", "core.quotepath=false", "status", "--porcelain", "--untracked-files=all", "--", *LANGS])
    files, blocked, descs_changed = [], [], []
    for line in out.splitlines():
        status, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:  # 改名：取新路径
            path = path.split(" -> ", 1)[1].strip('"')
        p = ROOT / path
        if "D" in status or not p.exists() or p.name.startswith("."):
            continue
        if p.name == "descriptions.yml":  # 描述改动单独统计，不算素材
            descs_changed.append(p)
            continue
        files.append(p)
    videos = []
    for lang in LANGS:
        for p in (ROOT / lang).glob("**/*"):
            if p.is_file() and p.suffix.lower() in VIDEO_EXT:
                videos.append(p)
            elif p.is_file() and p.suffix.lower() in BLOCKED_EXT:
                rel = p.relative_to(ROOT).parts
                if not (rel[1:3] == ("brand", "logo") and p.suffix.lower() in LOGO_VECTOR_EXT):
                    blocked.append(p)
    return {"files": files, "videos": sorted(videos), "blocked": sorted(blocked), "descs": descs_changed}


def video_target(p: Path) -> tuple[str, str, str] | None:
    """视频 → (Release 标签, Release 标题, 规范文件名)；不在某个 videos/ 文件夹下返回 None。
    products/<型号>/videos、solutions/<方案>/videos、brand/videos"""
    loc = locate(p.relative_to(ROOT).as_posix())
    if "error" in loc or loc["kind"] != "videos":
        return None
    lang, section, owner = loc["lang"], loc["section"], loc["owner"]
    if owner:  # 按统一后的文件夹名（官网写法）计算，与上传时 canonicalize_folders 的结果一致
        index = load_categories() if section == "products" else load_solutions()
        info = index.get(lang, {}).get(model_key(owner))
        owner = (info.get("model") or info.get("solution")) if info else re.sub(r"\s+", "-", owner.strip())
    prefix = owner or loc["prefix"]
    return (release_tag(section, owner, lang), release_title(section, owner, lang),
            video_stem(p.stem, lang, prefix) + p.suffix.lower())


def check(compress: str | None = None) -> int:
    say(f"上传模式：{MODE_TEXT[compress]}\n")
    say("━━ 第 1 步：检查环境 ━━")
    if not doctor(quiet=True):
        return 1
    say("  ✓ 环境正常\n")

    say("━━ 第 2 步：盘点待上传内容 ━━")
    items = pending()
    inbox = [p for p in INBOX.glob("**/*") if p.is_file() and not p.name.startswith(".")] if INBOX.exists() else []
    if items["descs"]:
        say(f"  · 素材描述有更新：{len(items['descs'])} 个文件夹")
    if not items["files"] and not items["videos"] and not items["descs"]:
        say("  没有发现新的素材。请把文件放进 zh/ 或 en/ 下对应型号的 images / brochures / videos 文件夹。")
    for p in items["files"]:
        say(f"  · {p.relative_to(ROOT).as_posix()}（{mb(p.stat().st_size)}）")
    problems = []
    for p in items["videos"]:
        t = video_target(p)
        size = p.stat().st_size
        if not t:
            problems.append(f"{p.relative_to(ROOT).as_posix()}：视频要放在 products/<型号>/videos、solutions/<方案>/videos 或 brand/videos 下")
        elif size > RELEASE_LIMIT:
            problems.append(f"{p.relative_to(ROOT).as_posix()}：{mb(size)}，超过 2 GB，请先压缩视频")
        else:
            say(f"  · 视频 {p.relative_to(ROOT).as_posix()}（{mb(size)}）→ 将上传到 Release「{t[1]}」，文件名 {t[2]}")
    for p in items["blocked"]:
        problems.append(f"{p.relative_to(ROOT).as_posix()}：{BLOCKED_EXT[p.suffix.lower()]}不上传，请移走")
    if inbox:
        say(f"\n  「待上传」文件夹里还有 {len(inbox)} 个文件没归类（需要先用「整理素材」归类，或手动放进型号文件夹）。")

    say(f"\n━━ 第 3 步：预览自动整理（{MODE_TEXT[compress]}，不修改文件）━━")
    if compress == "new":
        lines = compress_files(images_of(items["files"]), dry_run=True)
        say("  将压缩这些新图片：")
        say("\n".join(f"    {x}" for x in lines) or "    无（没有新图片）")
    flags = ["--compress"] if compress == "all" else []
    changes, warns = build_report(run([sys.executable, "scripts/build.py", "--dry-run", *flags], check=False))
    if compress == "new":  # 预览时图片还没压缩，改名结果里的扩展名按压缩后显示
        srcs = {
            p.relative_to(ROOT).as_posix(): (".jpeg" if p.suffix.lower() == ".jpeg" and compressed_ext(p) == ".jpg"
                                             else compressed_ext(p))
            for p in images_of(items["files"])
        }
        changes = [
            c.rsplit(".", 1)[0] + srcs[c[2:].split(" → ")[0]] if " → " in c and c[2:].split(" → ")[0] in srcs else c
            for c in changes
        ]
    # 本地 videos/ 里待上传的视频是正常的，不显示"不放进仓库"的提醒
    local_videos = {p.relative_to(ROOT).as_posix() for p in items["videos"]}
    warns = [w for w in warns if not any(f"`{v}`" in w for v in local_videos)]
    say("  上传时会自动做这些整理：")
    say("\n".join(f"    {c}" for c in changes) or "    无")
    if warns:
        say("\n  注意事项（不影响上传，但建议处理）：")
        say("\n".join(f"    {w}" for w in warns))
    if problems:
        say("\n━━ 需要先处理的问题 ━━")
        for x in problems:
            say(f"  ✗ {x}")
        return 1
    say("\n检查完成。确认无误后运行上传。")
    return 0


# ---------- 上传 ----------

def push(message: str | None, compress: str | None = None) -> int:
    say(f"上传模式：{MODE_TEXT[compress]}\n")
    say("━━ 第 1 步：检查环境 ━━")
    if not doctor(quiet=True):
        return 1
    say("  ✓ 环境正常")

    say("\n━━ 第 2 步：同步 GitHub 上的最新内容 ━━")
    # 未提交的、程序生成的视频说明文件可随时重新生成，先删掉，免得挡住同步
    untracked = run(["git", "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard",
                     "--", *(f"{lang}/products/*/videos/*.yml" for lang in LANGS)]).splitlines()
    for rel in untracked:
        p = ROOT / rel
        if "source: release" in p.read_text(encoding="utf-8"):
            p.unlink()
    run(["git", "checkout", "--", *GENERATED], check=False)
    git_net(["pull", "--rebase", "--autostash", "origin", "main"], check=True)
    say("  ✓ 已是最新")
    # 先把型号 / 方案文件夹名统一成官网写法，视频的 Release 标签才会正确
    renamed, _ = canonicalize_folders(False, load_categories(), load_solutions())
    for c in renamed:
        say(f"  · 文件夹名统一：{c}")

    items = pending()
    if items["blocked"]:
        say("\n✗ 发现不应上传的文件，请先移走：")
        for p in items["blocked"]:
            say(f"  · {p.relative_to(ROOT).as_posix()}（{BLOCKED_EXT[p.suffix.lower()]}）")
        return 1
    if not items["files"] and not items["videos"] and not items["descs"] and compress != "all":
        say("\n没有需要上传的新素材。")
        return 0

    repo = run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    uploaded_videos = []
    if not items["videos"]:
        say("\n━━ 第 3 步：上传视频到 Release ━━\n  本次没有视频")
    else:
        say(f"\n━━ 第 3 步：上传视频到 Release（共 {len(items['videos'])} 个）━━")
        say("  提示：视频较大时需要几分钟，请不要关闭窗口；国内网络中断时重新运行即可。")
        for p in items["videos"]:
            t = video_target(p)
            if not t:
                say(f"  ✗ 跳过 {p.relative_to(ROOT).as_posix()}：不在任何 videos 文件夹下")
                continue
            tag, title, name = t
            if subprocess.run(["gh", "release", "view", tag], cwd=ROOT, capture_output=True).returncode != 0:
                run(["gh", "release", "create", tag, "--title", title, "--latest=false",
                     "--notes", "视频由上传工具自动上传；文件名与说明文件由程序自动处理。"])
                say(f"  · 新建 Release {tag}")
            label = p.stem  # 原文件名（可含中文）作为附件显示名，也用作视频标题
            if p.name != name:
                rename_desc(p.parent, p.name, name)  # 视频描述跟着改名
                p = p.rename(p.with_name(name))
            say(f"  · 正在上传 {label} → {name}（{mb(p.stat().st_size)}）…")
            run(["gh", "release", "upload", tag, f"{p}#{label}", "--clobber"], capture=False)
            dest = UPLOADED / tag / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dest)
            uploaded_videos.append(f"{tag}/{name}")
            say(f"    ✓ 完成，本地文件已移到 {dest.relative_to(ROOT).as_posix()} 留底")
        token = run(["gh", "auth", "token"])
        run([sys.executable, "scripts/sync_releases.py"],
            env={"GITHUB_TOKEN": token, "GITHUB_REPOSITORY": repo})
        say("  ✓ 视频说明文件已生成")

    say(f"\n━━ 第 4 步：自动整理（{MODE_TEXT[compress]}）━━")
    if compress == "new":
        lines = compress_files(images_of(items["files"]), dry_run=False)
        say("\n".join(f"  {x}" for x in lines) or "  没有新图片需要压缩")
    flags = ["--compress"] if compress == "all" else []
    changes, warns = build_report(run([sys.executable, "scripts/build.py", *flags]))
    say("\n".join(f"  {c}" for c in changes) or "  无需整理")
    # 清单、画廊、缩略图统一由 GitHub 端生成；本地不提交，避免与自动提交冲突
    run(["git", "checkout", "--", *GENERATED], check=False)
    run(["git", "clean", "-fdq", "--", "_generated"], check=False)

    say("\n━━ 第 5 步：提交并推送到 GitHub ━━")
    run(["git", "add", "-A", "--", *LANGS])
    staged = run(["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--", *LANGS]).splitlines()
    if not staged and not uploaded_videos:
        say("  没有需要提交的变化。")
        return 0
    user = run(["git", "config", "user.name"], check=False) or "市场部"
    head = "整体压缩图片" if compress == "all" else "素材上传"
    msg = message or f"{head}：{len(staged)} 个文件" + (f"，{len(uploaded_videos)} 个视频" if uploaded_videos else "")
    run(["git", "commit", "-m", f"{msg}（{user}）"])
    for attempt in (1, 2):
        res = git_net(["push", "origin", "main"])
        if res.returncode == 0:
            break
        if attempt == 1:  # 期间别人或自动程序有提交：先合并（同一文件以本次上传为准）再推
            git_net(["pull", "--rebase", "-X", "theirs", "origin", "main"], check=True)
        else:
            raise SystemExit(f"✗ 推送失败：{res.stderr.strip()}\n请检查网络后重新运行上传。")
    say("  ✓ 已推送")

    say("\n━━ 完成 ━━")
    say(f"  · 新增/更新文件：{len(staged)} 个")
    if uploaded_videos:
        say(f"  · 上传视频：{len(uploaded_videos)} 个")
    say(f"  · 仓库：https://github.com/{repo}")
    links = access_links(repo, staged)
    if links:
        say("\n访问地址（「查看」是 GitHub 页面，可预览和下载；「下载」是直接下载链接，可以发给别人）：")
        say("\n".join(links))
        vis = run(["gh", "repo", "view", "--json", "visibility", "--jq", ".visibility"], check=False)
        if vis.upper() != "PUBLIC":
            say("  （仓库目前是私有的，登录 GitHub 且有权限的人才能打开）")
    if warns:
        say("\n注意事项（不影响本次上传，但请处理）：")
        say("\n".join(f"  {w}" for w in warns))
    return 0


# ---------- 描述 ----------

def describe_missing(all_: bool) -> int:
    """列出没有描述的素材：默认只列待上传的（新图片、本地视频），--all 列出仓库里全部"""
    if all_:
        collect(True, load_categories())
        paths = [ROOT / m for m in build.missing_desc]
    else:
        items = pending()
        paths = items["files"] + items["videos"]
        paths = [p for p in paths if not read_descs(p.parent).get(p.name)]
    if not paths:
        say("所有素材都已有描述。")
        return 0
    say(f"以下 {len(paths)} 个素材没有描述（语言按所在文件夹：zh 写中文，en 写英文）：")
    for p in paths:
        rel = p.relative_to(ROOT).as_posix()
        kind = "视频" if p.suffix.lower() in VIDEO_EXT or rel.endswith(".yml") else "图片" if p.suffix.lower() in IMAGE_EXT else "文件"
        facts = ""
        if kind == "图片":  # 透明背景在预览里看起来是白底，由程序判断后告诉写描述的人
            with Image.open(p) as im:
                facts = f"  [{im.width}×{im.height}，{'透明背景' if has_alpha(im) else '不透明'}]"
        say(f"  {kind}  {rel}{facts}")
    return 0


def describe(file: str, text: str) -> int:
    """写入一条描述到所在文件夹的 descriptions.yml（键为文件名）"""
    p = Path(file)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        say(f"✗ 找不到文件：{file}")
        return 1
    descs = read_descs(p.parent)
    descs[p.name] = " ".join(text.split())
    write_descs(p.parent, descs)
    say(f"✓ {p.relative_to(ROOT).as_posix()}：{descs[p.name]}")
    return 0


# ---------- 归类（skill 2 用）----------

def place(files: list[str], lang: str, model: str | None, solution: str | None, brand: str | None,
          kind: str | None, force: bool) -> int:
    """把文件放进 <lang>/products/<型号>/<类型>/、<lang>/solutions/<方案>/<类型>/ 或 <lang>/brand/<子文件夹>/。
    lang=both：中英文各放一份（无文字的图片用）"""
    langs = list(LANGS) if lang == "both" else [lang]
    if brand:
        section, owner, index, what = "brand", None, None, ""
    elif solution:
        section, owner, index, what = "solutions", solution, load_solutions(), "方案"
    else:
        section, owner, index, what = "products", model, load_categories(), "型号"
    canonical = owner
    for lg in langs:
        if index is None:
            break
        info = index.get(lg, {}).get(model_key(owner))
        if info:
            canonical = info.get("model") or info.get("solution")
        elif not force:
            other = "en" if lg == "zh" else "zh"
            hint = f"（该{what}只在另一种语言的官网上架）" if model_key(owner) in index.get(other, {}) else ""
            site = "中文" if lg == "zh" else "英文"
            listname = "产品列表" if section == "products" else "解决方案列表"
            say(f"✗ {what} {owner} 不在{site}官网{listname}中{hint}。确认无误可加 --force。")
            return 1
    for f in files:
        for i, lg in enumerate(langs):
            last = i == len(langs) - 1
            if place_one(f, lg, section, canonical, brand, kind, copy=not last):
                return 1
    return 0


def place_one(f: str, lang: str, section: str, owner: str | None, brand: str | None,
              kind: str | None, copy: bool) -> int:
    src = Path(f)
    if not src.is_absolute():
        src = ROOT / src
    if not src.is_file():
        say(f"✗ 找不到文件：{f}")
        return 1
    ext = src.suffix.lower()
    if section == "brand":
        k = "videos" if ext in VIDEO_EXT else brand
    else:
        k = kind or ("images" if ext in IMAGE_EXT else "videos" if ext in VIDEO_EXT else
                     "brochures" if ext in DOC_EXT else None)
    if k is None:
        say(f"✗ {src.name}：无法判断类型，请用 --type 指定 images / brochures / videos")
        return 1
    logo_vector = section == "brand" and k == "logo" and ext in LOGO_VECTOR_EXT
    if ext in BLOCKED_EXT and ext not in VIDEO_EXT and not logo_vector:
        say(f"✗ {src.name}：{BLOCKED_EXT[ext]}不上传")
        return 1
    if ext not in VIDEO_EXT and src.stat().st_size > MAX_BYTES:
        say(f"! {src.name}：{mb(src.stat().st_size)}，超过 20 MB，建议先压缩")
    if section == "brand":
        k = "videos" if ext in VIDEO_EXT else brand
        dest = ROOT / lang / "brand" / k / src.name
    else:
        dest = ROOT / lang / section / owner / k / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        say(f"✗ 目标已存在：{dest.relative_to(ROOT).as_posix()}")
        return 1
    (shutil.copy2 if copy else shutil.move)(str(src), dest)
    say(f"✓ {src.name} → {dest.relative_to(ROOT).as_posix()}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # 「待上传」只在本地使用、不进仓库：没有就自动建一个
    INBOX.mkdir(exist_ok=True)
    ap = argparse.ArgumentParser(description="市场素材上传工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    for name in ("check", "push"):
        p = sub.add_parser(name)
        g = p.add_mutually_exclusive_group()
        g.add_argument("--compress", dest="compress", action="store_const", const="new",
                       help="压缩本次新上传的图片（长边 ≤2000px，转 JPG / 透明图 PNG）")
        g.add_argument("--compress-all", dest="compress", action="store_const", const="all",
                       help="整体压缩仓库里所有图片")
        if name == "push":
            p.add_argument("-m", "--message")
    p = sub.add_parser("describe-missing", help="列出没有描述的素材")
    p.add_argument("--all", action="store_true", help="列出仓库里全部没有描述的素材（默认只列待上传的）")
    p = sub.add_parser("describe", help="写入一条素材描述")
    p.add_argument("file")
    p.add_argument("text")
    p = sub.add_parser("place")
    p.add_argument("files", nargs="+")
    p.add_argument("--lang", choices=[*LANGS, "both"], required=True, help="both = 中英文各放一份")
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--model", help="产品型号，放到 products/<型号>/")
    who.add_argument("--solution", help="解决方案名，放到 solutions/<方案>/")
    who.add_argument("--brand", choices=list(BRAND_TYPES), help="品牌资料子文件夹，放到 brand/<子文件夹>/")
    p.add_argument("--type", dest="kind", choices=["images", "brochures", "videos"])
    p.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "doctor":
        return 0 if doctor() else 1
    if a.cmd == "describe-missing":
        return describe_missing(a.all)
    if a.cmd == "describe":
        return describe(a.file, a.text)
    if a.cmd == "check":
        return check(a.compress)
    if a.cmd == "push":
        return push(a.message, a.compress)
    return place(a.files, a.lang, a.model, a.solution, a.brand, a.kind, a.force)


if __name__ == "__main__":
    sys.exit(main())
