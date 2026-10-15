#!/usr/bin/env python3
"""把素材库单向同步到国内镜像：AWS 中国区 S3 桶 + CloudFront（https://media-hub.inhand.com.cn）。

GitHub 是主仓库；本脚本由 GitHub Actions 在每次整理后运行，也可本地运行：
    python scripts/sync_cn.py --dry-run                      # 只预览，不改任何东西
    python scripts/sync_cn.py --profile marketing-cn         # 本地用 AWS profile 运行
    python scripts/sync_cn.py --prefix _sync-test/ ...       # 测试：所有对象放到测试前缀下

同步内容（桶根目录与仓库结构一致）：
- zh/、en/ 下的素材文件（图片、宣传册、Logo 等）
- _generated/thumbs/ 缩略图；_generated/gallery/{zh,en}.cn.html → 国内版画廊 {zh,en}.html
- catalog.json、llms.txt、categories.yml
- 视频：从 GitHub Release 下载，按中文原名存到 <lang>/.../videos/<标题>.mp4（见 build.cn_video_keys）

规则：
- 只上传有变化的文件（普通文件比 MD5；视频比大小和 Release 更新时间）
- GitHub 上已删除的文件，国内也删除；删除只限本脚本管理的路径（zh/、en/、_generated/ 和三个清单文件）
- 只刷新有变化的 CDN 路径；变化很多时刷新一次 /*
凭据：GitHub Actions 用环境变量 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY；本地用 --profile。
"""
from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

import boto3
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import (  # noqa: E402
    BLOCKED_EXT, GEN, LANGS, LOGO_VECTOR_EXT, ROOT, SKIP_NAMES, cn_video_keys,
)

BUCKET = "inhandwww-resources"
REGION = "cn-north-1"
DISTRIBUTION = "E3NBEQNO59BHGE"          # media-hub.inhand.com.cn
ROOT_FILES = ["catalog.json", "llms.txt", "categories.yml"]
MANAGED_PREFIXES = [*(f"{lang}/" for lang in LANGS), "_generated/", *ROOT_FILES]
SHORT_CACHE = "public, max-age=300"       # 清单、画廊：5 分钟
LONG_CACHE = "public, max-age=86400"      # 素材：1 天（有变化时会刷新 CDN）
TYPES = {".svg": "image/svg+xml", ".webp": "image/webp", ".yml": "text/yaml", ".yaml": "text/yaml",
         ".md": "text/markdown", ".json": "application/json", ".txt": "text/plain", ".html": "text/html",
         ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".pdf": "application/pdf"}
TEXT_TYPES = ("text/", "application/json", "image/svg+xml")
INVALIDATE_ALL_OVER = 50                  # 变化路径超过这个数时只刷新一次 /*


def content_type(name: str) -> str:
    ext = Path(name).suffix.lower()
    t = TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return t + "; charset=utf-8" if t.startswith(TEXT_TYPES) else t


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_objects(prefix: str) -> dict[str, dict]:
    """应当存在于国内镜像的对象：key → {kind: file|video, ...}"""
    exp: dict[str, dict] = {}

    def add_file(src: Path, key: str, cache: str) -> None:
        exp[prefix + key] = {"kind": "file", "src": src, "cache": cache}

    for lang in LANGS:
        base = ROOT / lang
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.name in SKIP_NAMES or p.name.startswith("."):
                continue
            rel = p.relative_to(ROOT).as_posix()
            ext = p.suffix.lower()
            logo_vector = rel.split("/")[1:3] == ["brand", "logo"] and ext in LOGO_VECTOR_EXT
            if ext in BLOCKED_EXT and not logo_vector:
                continue  # 视频本身、设计源文件等不在仓库里同步（视频走下面的 Release 下载）
            if ext in (".yml", ".yaml") and p.parent.name == "videos":
                continue  # 视频说明文件只是元数据
            add_file(p, rel, LONG_CACHE)
        for videos_dir in sorted(d for d in base.rglob("videos") if d.is_dir()):
            for yml_name, key in cn_video_keys(videos_dir).items():
                meta = yaml.safe_load((videos_dir / yml_name).read_text(encoding="utf-8")) or {}
                exp[prefix + key] = {"kind": "video", "url": meta["download_global"],
                                     "bytes": int(meta.get("bytes") or 0),
                                     "updated": str(meta.get("updated_at") or "")}
    thumbs = GEN / "thumbs"
    if thumbs.is_dir():
        for p in sorted(thumbs.rglob("*")):
            if p.is_file():
                add_file(p, p.relative_to(ROOT).as_posix(), LONG_CACHE)
    for lang in LANGS:  # 国内版画廊以普通文件名发布，页面内相对链接不变
        g = GEN / "gallery" / f"{lang}.cn.html"
        if g.exists():
            add_file(g, f"_generated/gallery/{lang}.html", SHORT_CACHE)
    for name in ROOT_FILES:
        if (ROOT / name).exists():
            add_file(ROOT / name, name, SHORT_CACHE)
    return exp


def existing_objects(s3, prefix: str) -> dict[str, dict]:
    """桶里本脚本管理范围内现有的对象：key → {etag, size}"""
    found: dict[str, dict] = {}
    pager = s3.get_paginator("list_objects_v2")
    for managed in MANAGED_PREFIXES:
        for page in pager.paginate(Bucket=BUCKET, Prefix=prefix + managed):
            for o in page.get("Contents", []):
                key = o["Key"]
                if managed in ROOT_FILES and key != prefix + managed:
                    continue  # 根目录清单文件只精确匹配
                found[key] = {"etag": o["ETag"].strip('"'), "size": o["Size"]}
    return found


def video_up_to_date(s3, key: str, spec: dict, have: dict | None) -> bool:
    if not have or (spec["bytes"] and have["size"] != spec["bytes"]):
        return False
    head = s3.head_object(Bucket=BUCKET, Key=key)
    return head.get("Metadata", {}).get("source-updated", "") == spec["updated"]


def upload_video(s3, key: str, spec: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "video"
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "marketing-assets-sync"})
        with urllib.request.urlopen(req, timeout=600) as r, dst.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        s3.upload_file(str(dst), BUCKET, key, ExtraArgs={
            "ContentType": content_type(key), "CacheControl": LONG_CACHE,
            "Metadata": {"source-updated": spec["updated"]},
        })


def invalidate(cf, keys: list[str]) -> str:
    paths = ["/*"] if len(keys) > INVALIDATE_ALL_OVER else ["/" + quote(k, safe="/") for k in keys]
    r = cf.create_invalidation(DistributionId=DISTRIBUTION, InvalidationBatch={
        "Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": f"sync-{time.time():.0f}"})
    return f"{r['Invalidation']['Id']}（{len(paths)} 条路径）"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="同步素材库到国内镜像（AWS 中国区）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不改任何东西")
    ap.add_argument("--profile", help="本地 AWS profile（如 marketing-cn）；GitHub Actions 用环境变量凭据")
    ap.add_argument("--prefix", default="", help="仅测试用：所有对象放到这个前缀下，如 _sync-test/")
    ap.add_argument("--no-invalidate", action="store_true", help="不刷新 CDN 缓存")
    a = ap.parse_args()
    if a.prefix and not a.prefix.endswith("/"):
        a.prefix += "/"

    session = boto3.Session(profile_name=a.profile, region_name=REGION)
    s3, cf = session.client("s3"), session.client("cloudfront")

    exp = expected_objects(a.prefix)
    have = existing_objects(s3, a.prefix)
    to_upload, to_delete = [], sorted(set(have) - set(exp))
    for key, spec in sorted(exp.items()):
        if spec["kind"] == "file":
            if key not in have or have[key]["etag"] != md5(spec["src"]):
                to_upload.append(key)
        elif not video_up_to_date(s3, key, spec, have.get(key)):
            to_upload.append(key)

    print(f"国内镜像：s3://{BUCKET}/{a.prefix}（{'预览' if a.dry_run else '执行'}）")
    print(f"  应有 {len(exp)} 个对象，现有 {len(have)} 个；上传 {len(to_upload)} 个，删除 {len(to_delete)} 个")
    for k in to_upload:
        print(f"  ↑ {k}{'（视频）' if exp[k]['kind'] == 'video' else ''}")
    for k in to_delete:
        print(f"  ✗ {k}")
    if a.dry_run or not (to_upload or to_delete):
        return 0

    for key in to_upload:
        spec = exp[key]
        if spec["kind"] == "video":
            upload_video(s3, key, spec)
        else:
            s3.put_object(Bucket=BUCKET, Key=key, Body=spec["src"].read_bytes(),
                          ContentType=content_type(key), CacheControl=spec["cache"])
    for i in range(0, len(to_delete), 1000):
        s3.delete_objects(Bucket=BUCKET, Delete={"Objects": [{"Key": k} for k in to_delete[i:i + 1000]]})
    print("  ✓ 同步完成")
    if not a.no_invalidate:
        print("  ✓ 已刷新 CDN 缓存：" + invalidate(cf, to_upload + to_delete))
    return 0


if __name__ == "__main__":
    sys.exit(main())
