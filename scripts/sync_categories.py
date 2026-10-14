#!/usr/bin/env python3
"""从官网自动生成 categories.yml（品类 → 系列 → 型号），中英文分开。

数据来源：官网 WordPress 公开接口（无需登录）
    https://www.inhand.com/wp-json/wp/v2/product_cat      英文站分类
    https://www.inhand.com/wp-json/wp/v2/product          英文站产品
    https://www.inhand.com.cn/wp-json/wp/v2/...            中文站同上

规则：
- 中文站、英文站的产品线不同，分别生成 zh / en 两份
- 芯片厂商这一层（TI、Rockchip 等）不作为系列，型号直接归到品类下
- 「解决方案」单独列为 solutions（对应 solutions/ 文件夹）；跳过「配件」「未分类」，以及标题带「复制 / copy」的草稿
- 型号 ID = 英文站产品标题，空格换成 "-"（如 "Mo 62A" → "Mo-62A"）；中文站同一产品
  （官网产品 ID 相同）沿用英文 ID，中文标题不同时记入 display_names，用于画廊显示

用法：python scripts/sync_categories.py            # 有变化才写文件
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "categories.yml"
SITES = {"zh": "https://www.inhand.com.cn", "en": "https://www.inhand.com"}
SKIP_CATEGORY_SLUGS = {"solutions", "accessories", "unassorted"}
# 芯片厂商子分类：不作为系列。官网新增厂商时在这里加一个名字
VENDORS = {"ti", "rockchip", "nvidia", "qualcomm", "nxp", "mediatek", "intel", "amd"}
DRAFT = re.compile(r"复制|copy", re.I)
CJK = re.compile(r"[一-鿿]")


def fetch_all(base: str, endpoint: str, fields: str) -> list[dict]:
    items, page = [], 1
    while True:
        url = f"{base}/wp-json/wp/v2/{endpoint}?per_page=100&page={page}&_fields={fields}"
        req = urllib.request.Request(url, headers={"User-Agent": "inhand-marketing-assets/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = json.load(resp)
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        items += batch
        if page >= total_pages:
            return items
        page += 1


def model_id(title: str) -> str:
    return re.sub(r"\s+", "-", html.unescape(title).strip())


def build_solutions(base: str, id_map: dict[int, str]) -> tuple[list[str], dict[str, str], dict[int, str]]:
    """官网「解决方案」下的子分类 → (方案 ID 列表, 中文显示名, 分类ID→方案ID)。
    方案 ID = 英文站分类名，空格换成 "-"（如 "InVision ADAS" → "InVision-ADAS"）；中文站沿用英文 ID。"""
    cats = fetch_all(base, "product_cat", "id,name,slug,parent,count")
    root = next((c for c in cats if c["slug"] == "solutions" and not c["parent"]), None)
    if not root:
        return [], {}, {}
    ids, display = {}, {}
    for c in cats:
        if c["parent"] != root["id"] or not c["count"]:
            continue
        name = html.unescape(c["name"]).strip()
        sid = id_map.get(c["id"]) or model_id(name)
        ids[c["id"]] = sid
        if CJK.search(name):
            display[sid] = name
    return sorted(set(ids.values()), key=str.upper), dict(sorted(display.items())), ids


def build_site(base: str, id_map: dict[int, str]) -> tuple[list[dict], dict[str, str], dict[int, str]]:
    """返回 (品类树, 显示名, 产品ID→型号ID)。id_map 为英文站的产品ID→型号ID，用于中文站统一 ID。"""
    cats = fetch_all(base, "product_cat", "id,name,slug,parent")
    prods = fetch_all(base, "product", "id,title,slug,product_cat,link")
    by_id = {c["id"]: c for c in cats}

    def top_of(c: dict) -> dict:
        while c["parent"] and c["parent"] in by_id:
            c = by_id[c["parent"]]
        return c

    ids: dict[int, str] = {}
    display: dict[str, str] = {}
    tops = [c for c in cats if not c["parent"] and c["slug"] not in SKIP_CATEGORY_SLUGS]
    tree = {
        c["id"]: {"name": html.unescape(c["name"]), "slug": c["slug"], "series": {}, "models": set()}
        for c in tops
    }

    for p in prods:
        title = html.unescape(p["title"]["rendered"])
        if DRAFT.search(title) or DRAFT.search(p["slug"]):
            continue
        mid = id_map.get(p["id"]) or model_id(title)
        ids[p["id"]] = mid
        if CJK.search(title):
            display[mid] = title
        placed = set()
        for cid in p["product_cat"]:
            c = by_id.get(cid)
            if not c:
                continue
            top = top_of(c)
            node = tree.get(top["id"])
            if node is None:
                continue
            is_series = c["id"] != top["id"] and html.unescape(c["name"]).strip().lower() not in VENDORS
            if is_series:
                s = node["series"].setdefault(
                    c["id"], {"name": html.unescape(c["name"]), "slug": c["slug"], "models": set()}
                )
                s["models"].add(mid)
                placed.add(top["id"])
        # 只挂在品类或芯片厂商子分类下的型号 → 归到品类本身
        for cid in p["product_cat"]:
            c = by_id.get(cid)
            if c and top_of(c)["id"] in tree and top_of(c)["id"] not in placed:
                tree[top_of(c)["id"]]["models"].add(mid)

    result = []
    for top in sorted(tree.values(), key=lambda t: t["slug"]):
        entry: dict = {"name": top["name"], "slug": top["slug"]}
        series = [
            {"name": s["name"], "slug": s["slug"], "models": sorted(s["models"], key=str.upper)}
            for s in sorted(top["series"].values(), key=lambda s: s["slug"])
            if s["models"]
        ]
        if series:
            entry["series"] = series
        if top["models"]:
            entry["models"] = sorted(top["models"], key=str.upper)
        if series or top["models"]:
            result.append(entry)
    listed = {m for t in tree.values() for m in t["models"]}
    listed |= {m for t in tree.values() for s in t["series"].values() for m in s["models"]}
    display = {k: v for k, v in sorted(display.items()) if k in listed}
    return result, display, ids


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    en_tree, en_display, en_ids = build_site(SITES["en"], {})
    zh_tree, zh_display, _ = build_site(SITES["zh"], en_ids)
    en_sol, en_sol_display, en_sol_ids = build_solutions(SITES["en"], {})
    zh_sol, zh_sol_display, _ = build_solutions(SITES["zh"], en_sol_ids)
    data = {"zh": {"categories": zh_tree}, "en": {"categories": en_tree}}
    if zh_display:
        data["zh"]["display_names"] = zh_display
    if en_display:
        data["en"]["display_names"] = en_display
    for lang, sol, disp in (("zh", zh_sol, zh_sol_display), ("en", en_sol, en_sol_display)):
        if sol:
            data[lang]["solutions"] = sol
        if disp:
            data[lang]["solution_names"] = disp
    header = (
        "# 自动生成，请勿手改。来源：官网产品分类接口（scripts/sync_categories.py，每周同步）\n"
        "# zh = www.inhand.com.cn，en = www.inhand.com；两站产品线不同，分别列出\n"
        "# 结构：品类 → 系列 → 型号；没有系列的型号直接列在品类的 models 下；display_names = 中文显示名\n"
        "# solutions = 官网「解决方案」下的方案（solutions/ 文件夹名）；solution_names = 方案中文名\n\n"
    )
    text = header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if text == old:
        print("categories.yml 无变化")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    for lang in data:
        cats = data[lang]["categories"]
        n = sum(len(e.get("models", [])) + sum(len(s["models"]) for s in e.get("series", [])) for e in cats)
        print(f"{lang}: {len(cats)} 个品类，{n} 个型号")
    print("categories.yml 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
