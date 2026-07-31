#!/usr/bin/env node
/*
 * Render the logo-grade evaluation sheet for one logo file.
 * Usage: node render_logo_sheet.js <logo.(svg|png|jpg)> <out.png>
 *
 * Cells: 256px reference | 48/32/16px | grayscale | one-color silhouette
 * (SVG only) | white-on-dark | 8px blur (squint / pre-attentive test).
 * SVG input is embedded as a base64 data: image, never inlined into the
 * page DOM. Needs playwright-core resolvable from this script (npm i
 * playwright-core in this directory or any ancestor) and Chromium at
 * /opt/pw-browsers/chromium (Claude Code web sandbox default).
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const [, , input, output] = process.argv;
if (!input || !output) {
  console.error("usage: node render_logo_sheet.js <logo> <out.png>");
  process.exit(2);
}

const KEEP = /^(none|transparent|url\()/i;

// Rewrite every fill/stroke paint to `color`, in attributes (either quote
// style) and inline CSS declarations, preserving none/transparent/url().
function transformPaints(svg, color) {
  return svg
    .replace(/(fill|stroke)="([^"]*)"/g, (m, prop, val) =>
      KEEP.test(val.trim()) ? m : `${prop}="${color}"`,
    )
    .replace(/(fill|stroke)='([^']*)'/g, (m, prop, val) =>
      KEEP.test(val.trim()) ? m : `${prop}='${color}'`,
    )
    .replace(/(fill|stroke)\s*:\s*([^;"'}<]+)/g, (m, prop, val) =>
      KEEP.test(val.trim()) ? m : `${prop}: ${color}`,
    );
}

function toDataUri(svg) {
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

const img = (src) => `<img src="${src}">`;

const isSvg = input.toLowerCase().endsWith(".svg");
let source, oneColor, whiteVersion;
if (isSvg) {
  const svg = fs.readFileSync(input, "utf8");
  source = img(toDataUri(svg));
  oneColor = img(toDataUri(transformPaints(svg, "#252220")));
  whiteVersion = img(toDataUri(transformPaints(svg, "#ffffff")));
} else {
  const RASTER_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
  };
  const mime = RASTER_MIME[path.extname(input).toLowerCase()];
  if (!mime) {
    console.error(`unsupported input type: ${input}`);
    process.exit(2);
  }
  const uri = `data:${mime};base64,${fs.readFileSync(input).toString("base64")}`;
  source = img(uri);
  oneColor = null;
  whiteVersion = source;
}

function cell(label, inner, opts = {}) {
  const bg = opts.dark ? "#171717" : "#ffffff";
  const fg = opts.dark ? "#999" : "#666";
  const filter = opts.filter ? `filter:${opts.filter};` : "";
  const w = opts.w || 200;
  const size = opts.inner || w - 24;
  return `<div style="display:flex;flex-direction:column;align-items:center;gap:6px">
    <div style="width:${w}px;height:${w}px;background:${bg};display:flex;
      align-items:center;justify-content:center;border:1px solid #ddd">
      <div style="width:${size}px;height:${size}px;${filter}">${inner}</div>
    </div>
    <span style="font:11px monospace;color:${fg}">${label}</span></div>`;
}

const cells = [
  cell("256px", source, { w: 260, inner: 236 }),
  cell("48px", source, { w: 64, inner: 48 }),
  cell("32px", source, { w: 48, inner: 32 }),
  cell("16px", source, { w: 32, inner: 16 }),
  cell("grayscale", source, { filter: "grayscale(1)" }),
  oneColor ? cell("one-color", oneColor) : "",
  cell("white-on-dark", whiteVersion, { dark: true }),
  cell("blur 8px (squint)", source, { filter: "blur(8px)" }),
].join("");

(async () => {
  const browser = await chromium.launch({
    executablePath: "/opt/pw-browsers/chromium",
  });
  const page = await browser.newPage({ viewport: { width: 1160, height: 640 } });
  await page.setContent(
    `<style>img{width:100%;height:100%;object-fit:contain}</style>
    <body style="margin:0;padding:16px;background:#f5f5f5;display:flex;
      flex-wrap:wrap;gap:16px;align-items:flex-end">${cells}</body>`,
  );
  await page.waitForTimeout(250);
  await page.screenshot({ path: output, fullPage: true });
  await browser.close();
  console.log("sheet written:", output);
})().catch((e) => {
  console.error("ERR", e.message);
  process.exit(1);
});
