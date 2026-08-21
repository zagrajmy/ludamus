// Screenshots src/ludamus/static/og-card/ to src/ludamus/static/og-image.jpg.
//
//   mise run og-image
//
// The card page owns the markup, the painting, and the font; this only renders
// it. /design/ frames the same page, so the panel there cannot go stale.

import { existsSync, statSync } from "node:fs";
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

const CARD = join(REPO, "src", "ludamus", "static", "og-card", "index.html");
const OUTPUT = join(REPO, "src", "ludamus", "static", "og-image.jpg");
const WIDTH = 1200;
const HEIGHT = 630;
const QUALITY = 86;

// Playwright's bundled Chromium; the sandbox image pre-installs it here. Off
// the sandbox, fall back to whatever playwright-core resolves locally.
const SANDBOX_CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const CHROME =
  process.env.OG_CHROME_PATH ??
  (existsSync(SANDBOX_CHROME) ? SANDBOX_CHROME : chromium.executablePath());

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--no-sandbox", "--font-render-hinting=none"],
});
try {
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 2,
  });
  await page.goto(pathToFileURL(CARD).href);
  // A missing face or painting must fail the build, not bake a fallback in.
  await page.waitForFunction(() =>
    document.fonts.ready.then(() => document.fonts.check("500 46px Outfit")),
  );
  await page.waitForFunction(() => {
    const url = /url\("([^"]+)"\)/.exec(
      getComputedStyle(document.querySelector(".card__art")).backgroundImage,
    )?.[1];
    return url
      ? fetch(url).then(
          (r) => r.ok,
          () => false,
        )
      : false;
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
