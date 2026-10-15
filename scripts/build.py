#!/usr/bin/env python3
"""整理素材并生成清单。

由 GitHub Actions 在每次同步后运行，也可本地运行：
    python scripts/build.py              # 整理（改名）+ 生成，图片保留原样
    python scripts/build.py --compress   # 另外把所有图片压到长边 2000px，转 JPG（有透明背景的转 PNG）（整体压缩）
    python scripts/build.py --dry-run    # 只检查，不改任何文件

做的事情：
1. 文件名规范化：补型号前缀、补语言后缀 _ZH/_EN、空格改为 "_"
2. 生成缩略图；仅 --compress 时图片长边压到 MAX_EDGE 以内，转 JPG（有透明背景的转 PNG）
3. 生成 catalog.json（素材清单）、llms.txt（给 AI 的索引）、中英文素材画廊
4. 发现问题写入 _generated/report.md（不阻断，由 workflow 开 issue 提醒）
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import yaml
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "_generated"
LANGS = {"zh": "ZH", "en": "EN"}
SECTIONS = ("products", "solutions", "brand")
PRODUCT_TYPES = ("images", "brochures", "videos")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
SKIP_NAMES = {".gitkeep", "README.md", "descriptions.yml"}
# 不应进仓库的文件（与 .gitignore 对应；网页上传不受 .gitignore 限制，这里再查一遍）
BLOCKED_EXT = {
    ".mp4": "视频", ".mov": "视频", ".m4v": "视频", ".avi": "视频", ".mkv": "视频",
    ".wmv": "视频", ".flv": "视频", ".webm": "视频", ".mpg": "视频", ".mpeg": "视频",
    ".psd": "设计源文件", ".psb": "设计源文件", ".ai": "设计源文件", ".indd": "设计源文件",
    ".sketch": "设计源文件", ".cdr": "设计源文件", ".eps": "设计源文件", ".heic": "原图",
    ".raw": "原图", ".cr2": "原图", ".nef": "原图", ".dng": "原图",
    ".stp": "3D 文件", ".step": "3D 文件", ".dwg": "图纸",
    ".rar": "压缩包", ".7z": "压缩包", ".iso": "安装包", ".exe": "安装包",
}
# 例外：brand/logo/ 下允许矢量 Logo（合作伙伴做物料需要）
LOGO_VECTOR_EXT = {".ai", ".eps", ".svg", ".pdf"}
MAX_EDGE = 2000          # 网页尺寸图片长边上限（px）
THUMB_EDGE = 480         # 缩略图长边（px）
MAX_BYTES = 20 * 1024 * 1024  # 超过则提醒

# 下载地址前缀。CN_BASE_URL 为国内镜像地址（GitHub 仓库变量），设置后 catalog 写入 url_cn 和 cn_base_url
GLOBAL_BASE = os.environ.get(
    "GLOBAL_BASE_URL", "https://raw.githubusercontent.com/inhandnet/marketing-assets/main"
)
CN_BASE = os.environ.get("CN_BASE_URL", "")

LANG_TOKEN = re.compile(r"^(ZH|EN)$", re.I)
VERSION_TOKEN = re.compile(r"^V\d+(\.\d+)*$", re.I)  # 只认 V1、V02、V1.0、V2.3.1 这种版本号


def write_lf(path: Path, text: str) -> None:
    """统一 LF 换行写文件：Windows 本地和 CI 生成的内容逐字节一致，避免来回改动"""
    path.write_text(text, encoding="utf-8", newline="\n")


DESC_FILE = "descriptions.yml"
DESC_HEADER = "# 素材描述：文件名 → 一句话说明画面内容和用途。上传时由 Claude 看图生成，可以直接修改\n"
missing_desc: list[str] = []  # collect() 填充：没有描述的素材


def read_descs(folder: Path) -> dict[str, str]:
    f = folder / DESC_FILE
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def write_descs(folder: Path, descs: dict[str, str]) -> None:
    if not descs:
        (folder / DESC_FILE).unlink(missing_ok=True)
        return
    body = yaml.safe_dump(dict(sorted(descs.items())), allow_unicode=True, sort_keys=False, width=1000)
    write_lf(folder / DESC_FILE, DESC_HEADER + body)


def rename_desc(folder: Path, old: str, new: str) -> None:
    """文件改名时，描述的键跟着改"""
    descs = read_descs(folder)
    if old in descs and old != new:
        descs[new] = descs.pop(old)
        write_descs(folder, descs)


def model_key(model: str) -> str:
    """型号比对时忽略大小写、空格和连字符：Mo 62A / MO62A / Mo-62A 视为同一型号"""
    return re.sub(r"[^0-9A-Z一-鿿]", "", model.upper())


def load_categories() -> dict[str, dict[str, dict]]:
    """语言 → 型号 key → {model, category, category_slug, series, display_name}"""
    data = yaml.safe_load((ROOT / "categories.yml").read_text(encoding="utf-8"))
    index: dict[str, dict[str, dict]] = {}
    for lang, site in data.items():
        names = site.get("display_names") or {}
        index[lang] = {}

        def add(model: str, cat: dict, series: dict | None) -> None:
            index[lang][model_key(model)] = {
                "model": model,
                "display_name": names.get(model, model.replace("-", " ")),
                "category": cat["name"],
                "category_slug": cat["slug"],
                "series": series["name"] if series else None,
            }

        for cat in site["categories"]:
            for model in cat.get("models", []):
                add(model, cat, None)
            for series in cat.get("series", []):
                for model in series["models"]:
                    add(model, cat, series)
    return index


# products 同级的另外两个栏目
SECTION_LABEL = {
    "solutions": {"zh": "解决方案", "en": "Solutions"},
    "brand": {"zh": "品牌资料", "en": "Brand"},
}
# brand/ 下的固定子文件夹 → (中文名, 英文名)
BRAND_TYPES = {
    "logo": ("Logo", "Logo"),
    "vi": ("VI 规范 / 品牌手册", "Brand guidelines"),
    "templates": ("PPT / Word 模板", "Templates"),
    "company": ("公司介绍 / 画册 / 资质荣誉", "Company profile"),
    "videos": ("公司宣传片", "Corporate videos"),
}
BRAND_PREFIX = "InHand"


def load_solutions() -> dict[str, dict[str, dict]]:
    """语言 → 方案 key → {solution, display_name, category}（方案列表来自官网「解决方案」分类）"""
    data = yaml.safe_load((ROOT / "categories.yml").read_text(encoding="utf-8"))
    index: dict[str, dict[str, dict]] = {}
    for lang, site in data.items():
        names = site.get("solution_names") or {}
        index[lang] = {
            model_key(sid): {
                "solution": sid,
                "display_name": names.get(sid, sid.replace("-", " ")),
                "category": SECTION_LABEL["solutions"][lang],
            }
            for sid in site.get("solutions", [])
        }
    return index


def locate(rel: str) -> dict:
    """按路径判断素材归属。返回 {lang, section, owner, kind, prefix}，放错位置时返回 {error}。
    products/<型号>/<类型>/文件、solutions/<方案>/<类型>/文件、brand/<子文件夹>/文件"""
    parts = rel.split("/")
    lang, section = parts[0], parts[1] if len(parts) > 2 else None
    if section == "products" or section == "solutions":
        what = "型号" if section == "products" else "方案"
        if len(parts) != 5:
            return {"error": f"应放在 {lang}/{section}/<{what}>/<images|brochures|videos>/ 下"}
        if parts[3] not in PRODUCT_TYPES:
            return {"error": f"类型文件夹 `{parts[3]}` 不认识，应为 images / brochures / videos"}
        return {"lang": lang, "section": section, "owner": parts[2], "kind": parts[3], "prefix": parts[2]}
    if section == "brand":
        if len(parts) != 4 or parts[2] not in BRAND_TYPES:
            return {"error": f"应放在 {lang}/brand/<{' | '.join(BRAND_TYPES)}>/ 下"}
        return {"lang": lang, "section": "brand", "owner": None, "kind": parts[2], "prefix": BRAND_PREFIX}
    return {"error": "不在 products / solutions / brand 下，请移动"}


def release_tag(section: str, owner: str | None, lang: str) -> str:
    """视频所在的 Release 标签：型号 IR315-zh、方案 solution-IWOS-zh、品牌 brand-zh"""
    if owner and re.search(r"\s", owner):
        raise ValueError(f"文件夹名 `{owner}` 含空格，不能作为 Release 标签，请先运行整理（build.py）统一文件夹名")
    if section == "products":
        return f"{owner}-{lang}"
    if section == "solutions":
        return f"solution-{owner}-{lang}"
    return f"brand-{lang}"


def parse_tag(tag: str) -> tuple[str, str | None, str] | None:
    """release_tag 的逆运算 → (section, owner, lang)"""
    m = re.match(r"^(?P<body>.+)-(?P<lang>zh|en)$", tag)
    if not m:
        return None
    body, lang = m["body"], m["lang"]
    if body == "brand":
        return "brand", None, lang
    if body.startswith("solution-"):
        return "solutions", body[len("solution-"):], lang
    return "products", body, lang


def release_title(section: str, owner: str | None, lang: str) -> str:
    if section == "products":
        return f"{owner} 中文视频" if lang == "zh" else f"{owner} English videos"
    if section == "solutions":
        return f"解决方案 {owner} 中文视频" if lang == "zh" else f"Solution {owner} English videos"
    return "公司宣传片（中文）" if lang == "zh" else "InHand corporate videos (English)"


def normalize_stem(stem: str, lang: str, model: str | None) -> str:
    stem = re.sub(r"\s+", "_", stem.strip())
    if model:
        prefix = model.replace(" ", "-")
        end = model_prefix_end(stem, prefix)
        if end:
            rest = stem[end:]
            if rest and rest[0] not in "_-":
                rest = "_" + rest  # 型号与后文连写时补分隔：IR315宣传册 → IR315_宣传册
            stem = prefix + rest  # 型号写法统一，如 ec5350_promo → EC5350_promo，Mo_62A → Mo-62A
        else:
            stem = f"{prefix}_{stem}"
    tokens = stem.split("_")
    if not any(LANG_TOKEN.match(t) for t in tokens):
        pos = next((i for i, t in enumerate(tokens) if VERSION_TOKEN.match(t)), len(tokens))
        tokens.insert(pos, LANGS[lang])
    return "_".join(tokens)


def model_prefix_end(stem: str, prefix: str) -> int:
    """stem 以型号开头（忽略大小写、空格、_、-）时返回型号部分的结束位置，否则返回 0"""
    want = re.sub(r"[\s_-]", "", prefix).upper()
    got, i = "", 0
    while i < len(stem) and len(got) < len(want):
        if stem[i] not in " _-":
            got += stem[i].upper()
        i += 1
    if got != want or (i < len(stem) and stem[i].isdigit() and want[-1].isdigit()):
        return 0  # IR3150 不是 IR315
    return i


def video_stem(stem: str, lang: str, model: str) -> str:
    """Release 附件名只能用英文：GitHub 会把中文替换成 "."（如 IR315_._._ZH.mp4）。
    去掉非英文部分；没有剩下描述时用原名的短哈希，保证同一文件每次得到同一个名字。"""
    tokens = []
    for t in normalize_stem(stem, lang, model).split("_"):
        a = re.sub(r"[^A-Za-z0-9.\-]", "", t).strip(".-")
        if a:
            tokens.append(a)
    fixed = {model.replace(" ", "-").upper(), "ZH", "EN"}
    if not [t for t in tokens if t.upper() not in fixed and not VERSION_TOKEN.match(t)]:
        digest = hashlib.sha1(stem.encode("utf-8")).hexdigest()[:6]
        tokens.insert(1, f"Video-{digest}")
    return "_".join(tokens)


def has_alpha(im: Image.Image) -> bool:
    """图片是否真的用到了透明（全不透明的 RGBA 按无透明处理）"""
    if im.mode == "P":
        return "transparency" in im.info
    if "A" not in im.getbands():
        return False
    return im.getchannel("A").getextrema()[0] < 255


def compressed_ext(path: Path) -> str:
    """压缩后的格式：有透明背景 → PNG，其余 → JPG（兼容性最好：旧版 Office、WPS、微信、印刷厂都能打开）"""
    with Image.open(path) as im:
        return ".png" if has_alpha(im) else ".jpg"


def compress_image(src: Path, dst: Path) -> None:
    """长边缩到 MAX_EDGE 以内；JPG 质量 85，PNG 无损优化；保留色彩配置文件，按拍摄方向摆正"""
    with Image.open(src) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile") if im.mode != "CMYK" else None  # CMYK 的配置文件不能用在转换后的 RGB 上
    im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    extra = {"icc_profile": icc} if icc else {}
    if dst.suffix.lower() == ".png":
        if im.mode not in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
        im.save(dst, "PNG", optimize=True, **extra)
    else:
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.save(dst, "JPEG", quality=85, optimize=True, progressive=True, **extra)


def make_thumb(src: Path, dst: Path) -> None:
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.thumbnail((THUMB_EDGE, THUMB_EDGE))
        if im.mode not in ("RGB", "RGBA"):  # CMYK、调色板等模式先转换，WebP 才能保存
            im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        im.save(dst, "WEBP", quality=80)


CN_TITLE_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def cn_video_keys(videos_dir: Path) -> dict[str, str]:
    """一个 videos/ 文件夹里每个视频说明文件 → 国内镜像中的对象路径（中文原名）。
    文件名取说明文件的 title（即上传时的中文原名），去掉路径和 Windows 不允许的字符；
    同一文件夹里标题重复时，后面的加上附件编号区分。没有下载链接的说明文件跳过。"""
    out: dict[str, str] = {}
    used: set[str] = set()
    for yml in sorted(videos_dir.glob("*.yml"), key=lambda p: p.name):
        meta = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        if not meta.get("download_global"):
            continue
        ext = Path(meta.get("file") or "x.mp4").suffix.lower() or ".mp4"
        title = re.sub(r"\s+", " ", CN_TITLE_BAD.sub("-", str(meta.get("title") or yml.stem))).strip(" .") or yml.stem
        name = title + ext
        if name.lower() in used:  # 标题重复
            name = f"{title}（{Path(meta.get('file') or yml.stem).stem}）{ext}"
        used.add(name.lower())
        out[yml.name] = (videos_dir / name).relative_to(ROOT).as_posix()
    return out


def url(base: str, rel: str) -> str:
    return f"{base}/{quote(rel)}" if base else ""


def canonicalize_folders(dry_run: bool, categories: dict, solutions: dict) -> tuple[list[str], list[str]]:
    """型号 / 方案文件夹名统一成官网写法（MO62A、mo 62a → Mo-62A；iwos → IWOS）。
    同一型号出现多个写法的文件夹时合并到一起，避免重复文件夹和多个 Release。不认识的名字至少去掉空格。"""
    changes, warnings = [], []
    planned: set[str] = set()  # 预览时记录已计划的目标文件夹，后面同目标的显示为"合并"
    for lang in LANGS:
        for section, index, field in (("products", categories, "model"), ("solutions", solutions, "solution")):
            base = ROOT / lang / section
            if not base.is_dir():
                continue
            for d in sorted(p for p in base.iterdir() if p.is_dir()):
                info = index.get(lang, {}).get(model_key(d.name))
                canonical = info[field] if info else re.sub(r"\s+", "-", d.name.strip())
                if canonical == d.name:
                    continue
                target = base / canonical
                rel_from, rel_to = d.relative_to(ROOT).as_posix(), target.relative_to(ROOT).as_posix()
                if dry_run and rel_to in planned:
                    changes.append(f"{rel_from}/ 合并到 {rel_to}/")
                    continue
                planned.add(rel_to)
                if target.exists() and not target.samefile(d):
                    changes.append(f"{rel_from}/ 合并到 {rel_to}/")
                    if dry_run:
                        continue
                    for f in sorted(p for p in d.rglob("*") if p.is_file()):
                        dst = target / f.relative_to(d)
                        if f.name == DESC_FILE and dst.exists():  # 两边都有描述：合并
                            write_descs(dst.parent, {**read_descs(f.parent), **read_descs(dst.parent)})
                            f.unlink()
                            continue
                        if dst.exists():
                            warnings.append(f"`{f.relative_to(ROOT).as_posix()}`：合并时 `{rel_to}` 下已有同名文件，未移动")
                            continue
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        f.rename(dst)
                    for sub in sorted((p for p in d.rglob("*") if p.is_dir()), reverse=True):
                        if not any(sub.iterdir()):
                            sub.rmdir()
                    if not any(d.iterdir()):
                        d.rmdir()
                else:
                    changes.append(f"{rel_from}/ → {rel_to}/")
                    if not dry_run:
                        tmp = d.with_name(d.name + ".renaming")  # Windows 大小写不敏感：只改大小写也要经过临时名
                        d.rename(tmp)
                        tmp.rename(target)
    return changes, warnings


def collect(dry_run: bool, categories: dict, compress: bool = False) -> tuple[list[dict], list[str], list[str]]:
    solutions = load_solutions()
    assets: list[dict] = []
    changes, warnings = canonicalize_folders(dry_run, categories, solutions)
    missing_desc.clear()

    for lang in LANGS:
        lang_dir = ROOT / lang
        if not lang_dir.is_dir():
            continue
        # 按路径字符串排序：Windows 和 Linux 对 Path 的排序规则不同（是否区分大小写），统一后两边输出一致
        for path in sorted((p for p in lang_dir.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
            if path.name in SKIP_NAMES or path.name.startswith("."):
                continue
            rel = path.relative_to(ROOT).as_posix()
            logo_vector = rel.split("/")[1:3] == ["brand", "logo"] and path.suffix.lower() in LOGO_VECTOR_EXT
            if path.suffix.lower() in BLOCKED_EXT and not logo_vector:
                warnings.append(
                    f"`{rel}`：{BLOCKED_EXT[path.suffix.lower()]}不放进仓库：视频请用上传工具或拖到对应的 Release 页面，设计源文件请留在设计部存档"
                )
                continue
            loc = locate(rel)
            if "error" in loc:
                warnings.append(f"`{rel}`：{loc['error']}")
                continue
            section, kind, prefix = loc["section"], loc["kind"], loc["prefix"]
            model = loc["owner"] if section == "products" else None
            solution = loc["owner"] if section == "solutions" else None
            site = "中文官网 inhand.com.cn" if lang == "zh" else "英文官网 inhand.com"
            if model and model_key(model) not in categories.get(lang, {}):
                warnings.append(f"`{rel}`：型号 `{model}` 不在{site}的产品列表中，请检查拼写或是否放错语言")
            if solution and model_key(solution) not in solutions.get(lang, {}):
                warnings.append(f"`{rel}`：方案 `{solution}` 不在{site}的解决方案列表中，请确认方案名称")
            if model or solution:  # 文件名前缀用官网写法（预览时文件夹可能还没统一）
                info = (categories if model else solutions).get(lang, {}).get(model_key(prefix))
                prefix = (info.get("model") or info.get("solution")) if info else re.sub(r"\s+", "-", prefix.strip())

            # 1) 规范文件名；compress 时图片转 JPG（有透明转 PNG）并压到长边 MAX_EDGE（默认保留原图）
            ext = path.suffix.lower()
            is_image = ext in IMAGE_EXT
            # Logo 需要保持高清（合作伙伴印刷、做物料），任何压缩都不处理 brand/logo/
            convert = compress and is_image and not (section == "brand" and kind == "logo")
            new_stem = normalize_stem(path.stem, lang, prefix)
            new_ext = compressed_ext(path) if convert else ext
            if new_ext == ".jpg" and ext == ".jpeg":
                new_ext = ext  # .jpeg 本来就是 JPG，保留原扩展名，链接不变
            target = path.with_name(new_stem + new_ext)
            if target != path:
                if target.exists():
                    warnings.append(f"`{rel}`：整理后的文件名 `{target.name}` 已存在，未处理")
                    continue
                changes.append(f"{rel} → {target.relative_to(ROOT).as_posix()}")
                if not dry_run:
                    if convert:
                        compress_image(path, target)
                        path.unlink()
                    else:
                        path.rename(target)
                    rename_desc(path.parent, path.name, target.name)  # 描述跟着文件改名
                    path = target
            elif convert:
                with Image.open(path) as im:
                    too_big = max(im.size) > MAX_EDGE
                if too_big:
                    changes.append(f"{rel}：压缩到长边 {MAX_EDGE}px")
                    if not dry_run:
                        compress_image(path, path)

            rel = path.relative_to(ROOT).as_posix()
            size = path.stat().st_size if path.exists() else 0
            if size > MAX_BYTES:
                tip = ("可以说「压缩并上传素材」压缩图片" if path.suffix.lower() in IMAGE_EXT
                       else "PDF 建议用 Acrobat「减小文件大小」或导出为较小尺寸后替换")
                warnings.append(f"`{rel}`：{size / 1048576:.1f} MB，超过 20 MB，{tip}")

            asset = {
                "path": rel,
                "lang": lang,
                "section": section,
                "type": kind,
                "model": model,
                "solution": solution,
                "format": path.suffix.lstrip(".").lower(),
                "bytes": size,
                "url": url(GLOBAL_BASE, rel),
                "url_cn": url(CN_BASE, rel),
            }
            if model:
                asset.update(categories.get(lang, {}).get(model_key(model), {}))
                asset["group"] = asset.get("model") or model
            elif solution:
                asset.update(solutions.get(lang, {}).get(model_key(solution), {}))
                asset.setdefault("category", SECTION_LABEL["solutions"][lang])
                asset["group"] = asset.get("solution") or solution
            else:
                asset["category"] = SECTION_LABEL["brand"][lang]
                asset["group"] = BRAND_TYPES[kind][0 if lang == "zh" else 1]

            # 2) 图片：尺寸 + 缩略图
            if path.exists() and path.suffix.lower() in IMAGE_EXT:
                with Image.open(path) as im:
                    asset["width"], asset["height"] = im.size
                # 缩略图统一为 WebP；非 WebP 原图在原名后追加 .webp，避免同名 jpg/png 撞车
                thumb = GEN / "thumbs" / (rel if rel.endswith(".webp") else rel + ".webp")
                if not dry_run:
                    make_thumb(path, thumb)
                asset["thumb"] = thumb.relative_to(ROOT).as_posix()

            # 3) 视频说明文件
            if path.suffix.lower() in (".yml", ".yaml") and kind == "videos":
                meta = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                asset["format"] = "video"
                asset["video"] = meta
                # 国内镜像里视频按中文原名存放（GitHub Release 附件名不能用中文）
                key = cn_video_keys(path.parent).get(path.name)
                if key:
                    asset["cn_key"] = key
                    asset["url_cn"] = url(CN_BASE, key)

            # 4) 描述（同目录 descriptions.yml：文件名 → 一句话描述；上传时由 Claude 看图生成，可人工修改）
            descs = read_descs(path.parent)
            video = asset.get("video", {})
            asset["description"] = (descs.get(path.name) or descs.get(video.get("file", ""))
                                    or video.get("description") or "")
            if not asset["description"]:
                missing_desc.append(rel)

            assets.append(asset)
    return assets, warnings, changes


def write_llms(assets: list[dict], categories: dict) -> None:
    lines = [
        "# InHand Networks 市场素材 / Marketing Assets",
        "",
        "> 映翰通公开市场素材：产品图片、宣传册、彩页规格书、视频，以及解决方案和品牌资料，按中文(zh)/英文(en)组织。",
        "> 机器可读的完整清单见 catalog.json；工程版规格书与手册见 https://github.com/inhandnet/documents",
        "",
    ]
    for lang, title in (("zh", "中文素材"), ("en", "English assets")):
        lines += [f"## {title} ({lang})", ""]
        groups: dict[tuple, list[dict]] = {}
        order = {"products": 0, "solutions": 1, "brand": 2}
        for a in assets:
            if a["lang"] == lang:
                groups.setdefault((order[a["section"]], a["group"]), []).append(a)
        for key in sorted(groups):
            first = groups[key][0]
            label = f"{first.get('display_name') or key[1]} — {first.get('category', '')}"
            if first.get("series"):
                label += f" / {first['series']}"
            lines += [f"### {label}", ""]
            for a in groups[key]:
                name = a.get("video", {}).get("title") or Path(a["path"]).name
                desc = f": {a['description']}" if a.get("description") else ""
                video = a.get("video", {})
                href = video.get("download_global") or a["url"]
                dims = f", {a['width']}×{a['height']}" if a.get("width") else ""
                lines.append(f"- [{name}]({href}) ({a['type']}, {a['format']}{dims}){desc}")
            lines.append("")
    write_lf(ROOT / "llms.txt", "\n".join(lines))


def write_gallery(assets: list[dict], categories: dict, cn: bool = False) -> None:
    """极简静态画廊：_generated/gallery/{zh,en}.html，可直接本地打开。
    cn=True 时生成国内镜像版 {zh,en}.cn.html：视频链接指向国内存储里的中文原名文件
    （同步到国内时改名为 zh.html / en.html，所以页面内的相对链接不变）。"""
    out_dir = GEN / "gallery"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = {
        "zh": ("映翰通市场素材", "下载", "其他", "English"),
        "en": ("InHand Marketing Assets", "Download", "Other", "中文"),
    }
    for lang in LANGS:
        title, dl, other, switch = text[lang]
        other_lang = "en" if lang == "zh" else "zh"
        groups: dict[str, dict[str, list[dict]]] = {}
        for a in assets:
            if a["lang"] != lang:
                continue
            cat = a.get("category") or other
            groups.setdefault(cat, {}).setdefault(a.get("display_name") or a["group"], []).append(a)
        body = []
        for cat in sorted(groups):
            body.append(f"<h2>{html.escape(cat)}</h2>")
            for key in sorted(groups[cat]):
                body.append(f"<h3>{html.escape(key)}</h3><div class='grid'>")
                for a in groups[cat][key]:
                    name = a.get("video", {}).get("title") or Path(a["path"]).name
                    if cn and a.get("cn_key"):
                        href = "../../" + quote(a["cn_key"])
                    else:
                        href = a.get("video", {}).get("download_global") or "../../" + quote(a["path"])
                    thumb = (
                        f"<img src='../../{quote(a['thumb'])}' alt='{html.escape(a.get('description') or name)}'>"
                        if a.get("thumb")
                        else f"<img src='../../{quote(a['path'])}' alt='{html.escape(a.get('description') or name)}'>"
                        if a["format"] == "svg"  # SVG 浏览器可直接显示，用原图当缩略图
                        else f"<div class='ph'>{html.escape(a['type'])}</div>"
                    )
                    body.append(
                        f"<figure>{thumb}<figcaption>{html.escape(name)}<br>"
                        f"<a href='{href}' download>{dl}</a></figcaption></figure>"
                    )
                body.append("</div>")
        page = f"""<!doctype html><html lang="{lang}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#222}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #ddd;border-radius:8px;padding:8px}}
img,.ph{{width:100%;height:160px;object-fit:contain;background:#f5f5f5;border-radius:4px}}
.ph{{display:flex;align-items:center;justify-content:center;color:#888}}
figcaption{{font-size:13px;margin-top:6px;word-break:break-all}}</style>
<h1>{title} <small><a href="{other_lang}.html">{switch}</a></small></h1>
{''.join(body)}</html>"""
        write_lf(out_dir / f"{lang}{'.cn' if cn else ''}.html", page)


AGENT_SKILL_TEMPLATE = """---
{frontmatter}
---

# {name}

本 skill 与 Claude Code 共用同一份完整步骤：`.claude/skills/{name}/SKILL.md`。
**先读取该文件，然后严格按其中的步骤执行。**

在 Codex 中使用时：
- 文中「用 Read 打开图片」= 用查看图片的功能打开图片。
- 运行 `python scripts/upload.py push` 时需要写 `.git` 并联网，默认沙盒会拦截：请向用户申请在沙盒外运行该命令，同意后再执行。其余命令在沙盒内即可运行。
"""


def sync_agent_skills() -> None:
    """Codex 从 .agents/skills/ 读 skill：按 .claude/skills/ 自动生成「转向」文件，名字和触发描述保持一致"""
    src_root, dst_root = ROOT / ".claude" / "skills", ROOT / ".agents" / "skills"
    if not src_root.is_dir():
        return
    for src in sorted(src_root.glob("*/SKILL.md")):
        m = re.match(r"---\n(.*?)\n---\n", src.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        dst = dst_root / src.parent.name / "SKILL.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = AGENT_SKILL_TEMPLATE.format(frontmatter=m.group(1), name=src.parent.name)
        if not dst.exists() or dst.read_text(encoding="utf-8") != text:
            write_lf(dst, text)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不修改文件")
    ap.add_argument("--compress", action="store_true",
                    help="把仓库里所有图片压到长边 2000px、转 JPG/PNG（默认不压缩，保留原图）")
    args = ap.parse_args()

    categories = load_categories()
    assets, warnings, changes = collect(args.dry_run, categories, args.compress)

    if not args.dry_run:
        GEN.mkdir(exist_ok=True)
        sync_agent_skills()
        # 清理已删除文件的描述（视频的描述以视频文件名为键，对应同名的 .yml 说明文件）
        for lang in LANGS:
            for f in (ROOT / lang).rglob(DESC_FILE):
                descs = read_descs(f.parent)
                alive = {k: v for k, v in descs.items()
                         if (f.parent / k).exists() or (f.parent / (Path(k).stem + ".yml")).exists()}
                if alive != descs:
                    write_descs(f.parent, alive)
        # 清理原图已删除或改名（如整体压缩后 png → jpg）留下的旧缩略图
        keep = {ROOT / a["thumb"] for a in assets if a.get("thumb")}
        for t in (GEN / "thumbs").rglob("*") if (GEN / "thumbs").exists() else []:
            if t.is_file() and t not in keep:
                t.unlink()
        catalog = {"schema_version": 1, **({"cn_base_url": CN_BASE} if CN_BASE else {}), "assets": assets}
        write_lf(ROOT / "catalog.json", json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        write_llms(assets, categories)
        write_gallery(assets, categories)
        write_gallery(assets, categories, cn=True)

    report = ["# 素材自动检查报告", ""]
    report += ["## 自动整理", ""] + ([f"- {c}" for c in changes] or ["- 无"]) + [""]
    report += ["## 需要人工处理", ""] + ([f"- {w}" for w in warnings] or ["- 无"]) + [""]
    if missing_desc:  # 仅提示，不触发 issue：在 Claude Code 里说「补全素材描述」即可补上
        report += [f"## 没有描述的素材（{len(missing_desc)} 个，说「补全素材描述」可补上）", ""]
        report += [f"· {m}" for m in missing_desc] + [""]
    if not args.dry_run:
        write_lf(GEN / "report.md", "\n".join(report))
    print("\n".join(report))
    print(f"共 {len(assets)} 个素材，自动整理 {len(changes)} 项，提醒 {len(warnings)} 项，{len(missing_desc)} 个没有描述")
    return 0


if __name__ == "__main__":
    sys.exit(main())
