// Renders scripts/og-image/template.html to src/ludamus/static/og-image.jpg.
//
//   mise run og-image
//
// The background is Rick Guidice's cylindrical-colony painting for NASA Ames
// (public domain, NASA). It is fetched from Wikimedia Commons on first run and
// cached in .cache/ rather than committed, since only the rendered card ships.

import { existsSync, statSync } from "node:fs";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..");

// playwright-core lives in the e2e project rather than the root install, so
// resolve it from either place instead of requiring a second node_modules tree.
const { chromium } = await (async () => {
  const roots = [REPO, join(REPO, "tests", "e2e")];
  for (const root of roots) {
    try {
      const resolved = createRequire(join(root, "package.json")).resolve("playwright-core");
      const mod = await import(pathToFileURL(resolved).href);
      // playwright-core is CJS, so named exports may only exist on `default`.
      return mod.chromium ? mod : mod.default;
    } catch {
      /* try the next root */
    }
  }
  throw new Error(`playwright-core not found. Install it in one of:\n  ${roots.join("\n  ")}`);
})();

const PAINTING_URL = "https://upload.wikimedia.org/wikipedia/commons/9/94/Spacecolony3edit.jpeg";
const CACHE_DIR = join(HERE, ".cache");
const PAINTING = join(CACHE_DIR, "colony.jpg");
const BUILD_DIR = join(CACHE_DIR, "build");
const OUTPUT = join(REPO, "src", "ludamus", "static", "og-image.jpg");

// Matches the PL translation of base.html's default_description. Baked in, so
// the card is Polish-only; og:description still varies by locale at request time.
const TAGLINE = "Konwent bez chaosu w arkuszach";

// Polish typography forbids leaving a one-letter word (i, w, z, o, a, u) at the
// end of a line, so glue each to the word that follows.
const noOrphans = (text) => text.replace(/(^|\s)([aiouwz])\s+/gi, "$1$2 ");
const WIDTH = 1200;
const HEIGHT = 630;
const QUALITY = 86;

// Playwright's bundled Chromium; the sandbox image pre-installs it here.
const CHROME = process.env.OG_CHROME_PATH ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

async function ensurePainting() {
  if (existsSync(PAINTING)) return;
  process.stdout.write(`fetching painting from ${PAINTING_URL}\n`);
  const res = await fetch(PAINTING_URL);
  if (!res.ok) {
    throw new Error(`painting download failed: ${res.status} ${res.statusText}`);
  }
  await writeFile(PAINTING, Buffer.from(await res.arrayBuffer()));
}

async function main() {
  await mkdir(BUILD_DIR, { recursive: true });
  await ensurePainting();

  const [template, lockup] = await Promise.all([
    readFile(join(HERE, "template.html"), "utf8"),
    readFile(join(HERE, "lockup-body.svg"), "utf8"),
  ]);

  const html = template
    .replace("<!--LOCKUP_BODY-->", lockup)
    .replace("<!--TAGLINE-->", noOrphans(TAGLINE));

  // Render from a real file:// page so the painting and webfont both load.
  await writeFile(join(BUILD_DIR, "card.html"), html);
  await writeFile(join(BUILD_DIR, "colony.jpg"), await readFile(PAINTING));

  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--font-render-hinting=none"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 2,
    });
    await page.goto(`file://${join(BUILD_DIR, "card.html")}`);
    await page.waitForFunction(() => document.fonts.ready.then(() => true));
    await page.waitForFunction(() => {
      const art = getComputedStyle(document.querySelector(".card__art"));
      const url = /url\("([^"]+)"\)/.exec(art.backgroundImage)?.[1];
      if (!url) return false;
      return fetch(url)
        .then((r) => r.ok)
        .catch(() => false);
    });
    await page.locator(".card").screenshot({
      path: OUTPUT,
      type: "jpeg",
      quality: QUALITY,
      scale: "css",
    });
  } finally {
    await browser.close();
  }

  const { size } = statSync(OUTPUT);
  process.stdout.write(`wrote ${OUTPUT} (${WIDTH}x${HEIGHT}, ${(size / 1024).toFixed(1)} KiB)\n`);
}

await main();
