#!/usr/bin/env node
/*
 * Render the logo-grade evaluation sheet for one logo file.
 * Usage: node render_logo_sheet.js <logo.(svg|png|jpg)> <out.png>
 *
 * Cells: 256px reference | 48/32/16px | grayscale | one-color silhouette
 * (SVG only) | white-on-dark | 8px blur (squint / pre-attentive test).
 * Needs playwright-core (npm i playwright-core) and Chromium at
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

const isSvg = input.toLowerCase().endsWith(".svg");
let source;
if (isSvg) {
  source = fs.readFileSync(input, "utf8");
} else {
  const ext = path.extname(input).slice(1).replace("jpg", "jpeg");
  source = `<img src="data:image/${ext};base64,${fs
    .readFileSync(input)
    .toString("base64")}" style="width:100%">`;
}

const oneColor = isSvg
  ? source
      .replace(/fill="(?!none)[^"]*"/g, 'fill="#252220"')
      .replace(/stroke="(?!none)[^"]*"/g, 'stroke="#252220"')
  : null;
const whiteVersion = isSvg
  ? source
      .replace(/fill="(?!none)[^"]*"/g, 'fill="#ffffff"')
      .replace(/stroke="(?!none)[^"]*"/g, 'stroke="#ffffff"')
  : source;

function cell(label, inner, opts = {}) {
  const bg = opts.dark ? "#171717" : "#ffffff";
  const fg = opts.dark ? "#999" : "#666";
  const filter = opts.filter ? `filter:${opts.filter};` : "";
  const w = opts.w || 200;
  return `<div style="display:flex;flex-direction:column;align-items:center;gap:6px">
    <div style="width:${w}px;height:${w}px;background:${bg};display:flex;
      align-items:center;justify-content:center;border:1px solid #ddd">
      <div style="width:${opts.inner || w - 24}px;${filter}">${inner}</div>
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
    `<body style="margin:0;padding:16px;background:#f5f5f5;display:flex;
      flex-wrap:wrap;gap:16px;align-items:flex-end">${cells}</body>`
  );
  await page.waitForTimeout(250);
  await page.screenshot({ path: output, fullPage: true });
  await browser.close();
  console.log("sheet written:", output);
})().catch((e) => {
  console.error("ERR", e.message);
  process.exit(1);
});
