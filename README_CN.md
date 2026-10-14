# 映翰通市场素材库

映翰通（InHand Networks）公开的市场素材：产品图片、宣传册、彩页规格书、宣传视频、解决方案资料和品牌资料。
销售、渠道、合作伙伴、媒体和 AI 助手都可以从这里取用。

- **素材画廊**（按品类浏览、带缩略图、可直接下载）：[中文](https://inhandnet.github.io/marketing-assets/_generated/gallery/zh.html) · [English](https://inhandnet.github.io/marketing-assets/_generated/gallery/en.html)
- **中文素材**：[`zh/`](zh/)　**英文素材**：[`en/`](en/)
- **视频**：仓库右侧的 [Releases](../../releases)
- **工程版规格书、用户手册、认证文件、2D/3D 图纸**：见 [inhandnet/documents](https://github.com/inhandnet/documents)

## 素材在哪里

```
zh/                          中文素材（en/ 结构完全相同）
├── products/<型号>/          产品素材，型号与官网一致，如 IR315、EC5350
│   ├── images/               产品图、场景图、海报
│   ├── brochures/            宣传册、彩页规格书
│   └── videos/               视频说明（视频本身在 Releases）
├── solutions/<方案>/         解决方案素材，方案名与官网「解决方案」一致，如 IWOS
│   └── images/  brochures/  videos/
└── brand/                    品牌资料
    ├── logo/                 Logo（含 SVG 等矢量文件）
    ├── vi/                   VI 规范、品牌手册
    ├── templates/            PPT、Word 模板
    ├── company/              公司介绍、画册、资质荣誉
    └── videos/               公司宣传片说明（视频本身在 Releases）
```

**视频**在 [Releases](../../releases) 下载，每个产品、方案各有中文和英文一个：

| 内容 | Release 名称示例 |
| --- | --- |
| 产品视频 | 「IR315 中文视频」「IR315 English videos」 |
| 解决方案视频 | 「解决方案 IWOS 中文视频」「Solution IWOS English videos」 |
| 公司宣传片 | 「公司宣传片（中文）」「InHand corporate videos (English)」 |

文件名统一为 `<型号或方案>_<内容>_<ZH|EN>`，如 `IR315_宣传册_ZH.pdf`；品牌资料以 `InHand_` 开头。
每个素材都附有一句文字描述，见所在文件夹的 `descriptions.yml`。

## AI 取用

- `llms.txt`：按语言列出全部素材、描述和下载链接
- `catalog.json`：每个素材的型号 / 方案、品类、系列、类型、语言、尺寸、下载链接、描述
- `categories.yml`：品类 → 系列 → 型号、解决方案列表，每周从中英文官网自动同步

## 使用说明

- 本仓库素材可用于宣传、销售和推广映翰通（InHand Networks）的产品与解决方案，包括渠道伙伴的市场活动和媒体报道。
- 请勿修改 Logo，也不要修改产品外观或画面中的产品信息；使用时请勿暗示映翰通为第三方产品或服务背书。
- 其他用途或有疑问，请联系映翰通市场部。

---

映翰通市场部同事：上传方法见内部的《市场部操作手册》。
