#!/usr/bin/env python3
"""视频走 GitHub Releases：自动建版本、规范文件名、生成 videos/*.yml。

市场部只需打开对应型号的 Release 页面，把视频拖进去。其余由本脚本完成：
1. 为 zh/ en/ 下有 videos/ 子文件夹的型号 / 方案，以及品牌资料建 Release（标签 <型号>-zh 等），
   语言由标签决定，不靠文件名猜
2. Release 里的视频文件改成规范名：<型号>_<内容>_<ZH|EN>[_Vx.y].mp4
3. 每个视频生成 / 更新 <lang>/products/<型号>/videos/<文件名>.yml：
   自动字段（文件名、大小、下载链接）每次刷新；可选的人工字段（标题、描述）保留
4. Release 里已删除的视频，对应的 yml（带 source: release 标记）一并删除

需要环境变量 GITHUB_TOKEN、GITHUB_REPOSITORY（Actions 中自动提供）。
用法：python scripts/sync_releases.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import BRAND_PREFIX, LANGS, ROOT, parse_tag, release_tag, release_title, video_stem  # noqa: E402

API = "https://api.github.com"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm", ".mpg", ".mpeg"}
AUTO_FIELDS = ("source", "file", "bytes", "download_global", "updated_at")
RELEASE_BODY = {
    "zh": "把中文视频直接拖到本页（编辑 → 拖入文件 → 更新）。文件名、说明文件由程序自动处理。",
    "en": "Drag English videos onto this release (Edit → drop files → Update). Names and metadata are handled automatically.",
}


class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token

    def call(self, method: str, path: str, body: dict | None = None):
        url = path if path.startswith("http") else f"{API}/repos/{self.repo}{path}"
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp) if resp.status != 204 else None

    def releases(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self.call("GET", f"/releases?per_page=100&page={page}")
            out += batch
            if len(batch) < 100:
                return out
            page += 1


def owners() -> list[tuple[str, str | None, str]]:
    """需要 Release 的归属：每个型号、每个方案文件夹，以及品牌资料 → (section, owner, lang)"""
    out = []
    for lang in LANGS:
        for section in ("products", "solutions"):
            base = ROOT / lang / section
            if base.is_dir():
                # 只给有 videos/ 子文件夹的型号 / 方案预建 Release（避免公开的 Releases 页满是空条目；
                # 上传工具会按需自建）。含空格的文件夹名先跳过：build.py 会统一成官网写法，下一轮再建
                out += [(section, d.name, lang) for d in sorted(base.iterdir())
                        if d.is_dir() and (d / "videos").is_dir() and not re.search(r"\s", d.name)]
        if (ROOT / lang / "brand").is_dir():
            out.append(("brand", None, lang))
    return out


def videos_dir(section: str, owner: str | None, lang: str) -> Path:
    if section == "brand":
        return ROOT / lang / "brand" / "videos"
    return ROOT / lang / section / owner / "videos"


def sync(gh: GitHub, dry_run: bool) -> list[str]:
    log: list[str] = []
    releases = {r["tag_name"]: r for r in gh.releases()}

    # 1) 补建 Release
    for section, owner, lang in owners():
        tag = release_tag(section, owner, lang)
        if tag in releases:
            continue
        log.append(f"新建 Release `{tag}`")
        if not dry_run:
            releases[tag] = gh.call("POST", "/releases", {
                "tag_name": tag,
                "name": release_title(section, owner, lang),
                "body": RELEASE_BODY[lang],
                "make_latest": "false",
            })

    # 2) 规范文件名（只用英文，中文会被 GitHub 替换） + 3) 生成 yml
    seen: set[Path] = set()
    for tag, rel in releases.items():
        parsed = parse_tag(tag)
        if not parsed:
            continue
        section, owner, lang = parsed
        target_dir = videos_dir(section, owner, lang)
        prefix = owner or BRAND_PREFIX
        names = {a["name"] for a in rel.get("assets", [])}
        for asset in rel.get("assets", []):
            name = asset["name"]
            ext = Path(name).suffix.lower()
            if ext not in VIDEO_EXT:
                log.append(f"`{tag}` 中的 `{name}` 不是视频，已跳过")
                continue
            stem = Path(name).stem
            # 网页上传中文名视频时 GitHub 会改成 default.mp4（接口上传则把中文换成 "."），原名已丢失：
            # 用附件 ID 起唯一名字，避免多个 default 互相冲突；标题标记为待补
            placeholder = re.fullmatch(r"(default|[._\-]*)", stem.lower()) is not None or re.fullmatch(
                rf"{re.escape(prefix)}_(default|[._\-]+)_(ZH|EN)", stem, re.I) is not None
            if placeholder:
                stem = f"{prefix}_Video-{asset['id']}"
            want = video_stem(stem, lang, prefix) + ext
            if want != name and want not in names:
                log.append(f"`{tag}`：{name} → {want}")
                if not dry_run:
                    asset = gh.call("PATCH", f"/releases/assets/{asset['id']}", {"name": want})
                names.add(want)
                name = want if dry_run else asset["name"]

            yml = target_dir / f"{Path(name).stem}.yml"
            seen.add(yml)
            meta = yaml.safe_load(yml.read_text(encoding="utf-8")) if yml.exists() else {}
            meta = meta or {}
            auto = {
                "source": "release",
                "file": name,
                "bytes": asset["size"],
                "download_global": asset["browser_download_url"],
                "updated_at": asset["updated_at"],
            }
            manual = {k: v for k, v in meta.items() if k not in AUTO_FIELDS}
            # 标题优先用附件显示名（上传工具会存原中文文件名），否则由文件名推出
            if asset.get("label"):
                title = asset["label"]
            elif placeholder:
                title = f"{prefix} 视频（网页上传，原中文名已丢失，待补标题）"
            else:
                title = " ".join(t for t in Path(name).stem.split("_") if t.upper() not in ("ZH", "EN"))
            manual.setdefault("title", title)
            for key in ("duration", "subtitle", "description"):
                manual.setdefault(key, "")
            new = {**manual, **auto}
            if new != meta:
                log.append(f"更新 {yml.relative_to(ROOT).as_posix()}")
                if not dry_run:
                    yml.parent.mkdir(parents=True, exist_ok=True)
                    yml.write_text(
                        yaml.safe_dump(new, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n"
                    )

    # 4) 清理已删除视频的 yml
    for lang in LANGS:
        ymls = [*(ROOT / lang).glob("products/*/videos/*.yml"), *(ROOT / lang).glob("solutions/*/videos/*.yml"),
                *(ROOT / lang).glob("brand/videos/*.yml")]
        for yml in ymls:
            meta = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            if meta.get("source") == "release" and yml not in seen:
                log.append(f"删除 {yml.relative_to(ROOT).as_posix()}（Release 中已无此视频）")
                if not dry_run:
                    yml.unlink()
    return log


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("缺少 GITHUB_REPOSITORY / GITHUB_TOKEN，跳过 Release 同步")
        return 0
    log = sync(GitHub(repo, token), args.dry_run)
    print("\n".join(log) or "Release 无变化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
