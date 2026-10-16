# InHand Networks Marketing Assets

Public marketing assets from InHand Networks: product images, brochures, designed datasheets, promo videos,
solution materials and brand assets — for sales teams, channel partners, press and AI assistants.
Chinese version: [README_CN.md](README_CN.md).

- Gallery (browse by category, thumbnails, direct download): [English](https://inhandnet.github.io/marketing-assets/_generated/gallery/en.html) · [Chinese](https://inhandnet.github.io/marketing-assets/_generated/gallery/zh.html)
- Chinese assets: [`zh/`](zh/) · English assets: [`en/`](en/)
- Videos: [Releases](../../releases)
- Engineering datasheets, manuals, certificates and drawings: [inhandnet/documents](https://github.com/inhandnet/documents)

## Layout

```
en/                          English assets (zh/ has the same structure, in Chinese)
├── products/<MODEL>/        product assets; model names as on the website, e.g. IR315, EC5350
│   ├── images/              product photos, application scenes, posters
│   ├── brochures/           brochures and designed datasheets
│   └── videos/              video info (the video files are in Releases)
├── solutions/<SOLUTION>/    solution assets, one folder per solution, e.g. IWOS
│   └── images/  brochures/  videos/
└── brand/                   brand assets
    ├── logo/                logos, incl. SVG and other vector files
    ├── vi/                  visual identity and brand guidelines
    ├── templates/           PowerPoint and Word templates
    ├── company/             company profile, brochures, certificates and awards
    └── videos/              corporate video info (the video files are in Releases)
```

**Videos** are downloaded from [Releases](../../releases). Each product and solution has one release for English videos and one for Chinese videos:

| Content | English release name example |
| --- | --- |
| Product videos | IR315 English videos |
| Solution videos | Solution IWOS English videos |
| Corporate videos | InHand corporate videos (English) |

File names follow `<MODEL or SOLUTION>_<content>_<ZH|EN>`, e.g. `IR315_Brochure_EN.pdf`; brand assets start with `InHand_`.
Every asset has a one-line description in its folder's `descriptions.yml`.

## For AI and tooling

- `llms.txt` — index of all assets with descriptions and download links
- `catalog.json` — full manifest: model / solution, category, series, type, language, size, URL, description
- `categories.yml` — category → series → model lists, synced weekly from www.inhand.com and www.inhand.com.cn

Catalog, index and gallery are regenerated automatically on every change.

## Usage

- These assets may be used to promote and sell InHand Networks products and solutions, including partner
  marketing and press coverage.
- Do not alter the logos, the product appearance or product information shown in the images, and do not imply
  that InHand Networks endorses third-party products or services.
- For any other use or questions, please contact InHand Networks marketing.
