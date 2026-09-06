#!/usr/bin/env python3
"""
Rasterise docs/favicon.svg into the PNG icon set the manifest and iOS need.

    node scripts/make_icons.js      # not this; see below
    python3 scripts/make_icons.py

Uses the Chromium that ships with Playwright to screenshot the SVG at each size,
so there's no ImageMagick / cairosvg dependency. The maskable variant re-lays the
same art at 68% scale on a full-bleed field, keeping it clear of Android's
safe-zone crop.
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "docs", "favicon.svg")
OUT = os.path.join(ROOT, "docs", "icons")

# name -> (size, maskable?)
TARGETS = {
    "icon-192.png": (192, False),
    "icon-512.png": (512, False),
    "icon-maskable-512.png": (512, True),
    "apple-touch-icon-180.png": (180, False),
}

NODE_SNIPPET = r"""
const { chromium } = require(process.env.PW_PATH || 'playwright');
const jobs = JSON.parse(process.argv[1]);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium' });
  for (const j of jobs) {
    const page = await browser.newPage({ viewport: { width: j.size, height: j.size } });
    await page.goto('file://' + j.html);
    await page.waitForTimeout(220);
    await page.screenshot({ path: j.out, omitBackground: false });
    await page.close();
  }
  await browser.close();
})();
"""


def wrap(svg_markup, size, maskable):
    scale = 0.68 if maskable else 1.0
    return f"""<!DOCTYPE html><meta charset="utf-8">
<style>
  html,body {{ margin:0; padding:0; background:#0B0E14; }}
  .frame {{ width:{size}px; height:{size}px; display:grid; place-items:center;
            background:#0B0E14; overflow:hidden; }}
  .art {{ width:{size * scale:.0f}px; height:{size * scale:.0f}px; }}
  .art svg {{ width:100%; height:100%; display:block; {"border-radius:0;" if maskable else ""} }}
</style>
<div class="frame"><div class="art">{svg_markup}</div></div>"""


def main():
    os.makedirs(OUT, exist_ok=True)
    svg = open(SVG).read()
    jobs, tmpfiles = [], []
    for name, (size, maskable) in TARGETS.items():
        fd, path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w") as fh:
            fh.write(wrap(svg, size, maskable))
        tmpfiles.append(path)
        jobs.append({"html": path, "out": os.path.join(OUT, name), "size": size})

    subprocess.run(["node", "-e", NODE_SNIPPET, json.dumps(jobs)], check=True)
    for p in tmpfiles:
        os.unlink(p)

    for name in TARGETS:
        p = os.path.join(OUT, name)
        print(f"{name:<28} {os.path.getsize(p):>7,} bytes")


if __name__ == "__main__":
    main()
