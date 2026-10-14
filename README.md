# InHand Networks Marketing Assets

Public marketing assets from InHand Networks: product images, brochures, designed datasheets, promo videos,
solution materials and brand assets — for sales teams, channel partners, press and AI assistants.
中文说明见 [README_CN.md](README_CN.md).

- Gallery (browse by category, thumbnails, direct download): [English](https://inhandnet.github.io/marketing-assets/_generated/gallery/en.html) · [中文](https://inhandnet.github.io/marketing-assets/_generated/gallery/zh.html)
- Chinese assets: [`zh/`](zh/) · English assets: [`en/`](en/)
- Videos: [Releases](../../releases)
- Engineering datasheets, manuals, certificates and drawings: [inhandnet/documents](https://github.com/inhandnet/documents)

## Layout

```
<lang>/products/<MODEL>/images|brochures|videos/      product assets (model IDs as on the website)
<lang>/solutions/<SOLUTION>/images|brochures|videos/  solution assets (as listed under "Solutions" on the website)
<lang>/brand/logo|vi|templates|company|videos/        logos (incl. vector), brand guidelines, templates, company profile
```

`<lang>` is `zh` or `en`. Video files live in Releases, one per model / solution and language
(e.g. `IR315 English videos`, `Solution IWOS English videos`, `InHand corporate videos (English)`);
`videos/*.yml` holds their titles and download links. Every asset has a one-line description in its folder's
`descriptions.yml`.

## For AI and tooling

- `llms.txt` — index of all assets with descriptions and download links
- `catalog.json` — full manifest: model / solution, category, series, type, language, size, URL, description
- `categories.yml` — category → series → model and solution lists, synced weekly from www.inhand.com and www.inhand.com.cn

Catalog, index and gallery are regenerated automatically on every change.

## Usage

- These assets may be used to promote and sell InHand Networks products and solutions, including partner
  marketing and press coverage.
- Do not alter the logos, the product appearance or product information shown in the images, and do not imply
  that InHand Networks endorses third-party products or services.
- For any other use or questions, please contact InHand Networks marketing.
