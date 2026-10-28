import { type Browser, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

export type VisualDiff = { ratio: number; size: { a: number[]; b: number[] } };

export async function visualDiff(
  browser: Browser,
  testInfo: TestInfo,
  { name, a, b }: { name: string; a: Buffer; b: Buffer },
): Promise<VisualDiff> {
  const page = await browser.newPage();
  const result = await page.evaluate(
    async ([srcA, srcB]) => {
      const load = (src: string) =>
        new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = src;
        });
      const [imgA, imgB] = await Promise.all([load(srcA), load(srcB)]);
      const width = Math.min(imgA.width, imgB.width);
      const height = Math.min(imgA.height, imgB.height);
      const fullWidth = Math.max(imgA.width, imgB.width);
      const fullHeight = Math.max(imgA.height, imgB.height);
      // NOTE: two crops of one layout can land a pixel apart in rounding.
      // Past that, whatever only one image has (a field missing from the
      // other) counts as different instead of being cropped away.
      const slack = 2;
      const unshared =
        fullWidth - width > slack || fullHeight - height > slack
          ? fullWidth * fullHeight - width * height
          : 0;
      const pixels = (img: HTMLImageElement) => {
        const canvas = document.createElement("canvas");
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(img, 0, 0);
        return ctx.getImageData(0, 0, img.width, img.height).data;
      };
      const pa = pixels(imgA);
      const pb = pixels(imgB);
      // Luminance, not colour: a composited layer (the modal) draws text with
      // greyscale anti-aliasing where the page uses subpixel colour fringes,
      // so per-channel comparison flags every glyph edge on Linux.
      const luma = (px: Uint8ClampedArray, i: number) =>
        0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
      const hit = (x: number, ya: number, yb: number) =>
        Math.abs(luma(pa, (ya * imgA.width + x) * 4) - luma(pb, (yb * imgB.width + x) * 4)) > 32;
      // The same rounding can shift one crop's content a pixel down; compare
      // at the vertical offset (within the slack) where the two agree most.
      const count = (dy: number) => {
        let differing = 0;
        for (let y = 0; y < height; y += 1) {
          const yb = y + dy;
          if (yb < 0 || yb >= imgB.height) continue;
          for (let x = 0; x < width; x += 1) if (hit(x, y, yb)) differing += 1;
        }
        return differing;
      };
      let dy = 0;
      let differing = count(0);
      for (let shift = -slack; shift <= slack; shift += 1) {
        const found = shift === 0 ? differing : count(shift);
        if (found < differing) [dy, differing] = [shift, found];
      }
      const out = new ImageData(width, height);
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          const i = (y * width + x) * 4;
          const a = (y * imgA.width + x) * 4;
          const yb = y + dy;
          const red = yb >= 0 && yb < imgB.height && hit(x, y, yb);
          out.data[i] = red ? 230 : 180 + pa[a] * 0.25;
          out.data[i + 1] = red ? 30 : 180 + pa[a + 1] * 0.25;
          out.data[i + 2] = red ? 30 : 180 + pa[a + 2] * 0.25;
          out.data[i + 3] = 255;
        }
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d")!.putImageData(out, 0, 0);
      return {
        ratio: (differing + unshared) / (fullWidth * fullHeight),
        size: { a: [imgA.width, imgA.height], b: [imgB.width, imgB.height] },
        diff: canvas.toDataURL("image/png"),
      };
    },
    [
      `data:image/png;base64,${a.toString("base64")}`,
      `data:image/png;base64,${b.toString("base64")}`,
    ],
  );
  await page.close();

  const files = {
    [`${name}-a.png`]: a,
    [`${name}-b.png`]: b,
    [`${name}-diff.png`]: Buffer.from(result.diff.split(",")[1], "base64"),
  };
  for (const [file, body] of Object.entries(files)) {
    const filePath = testInfo.outputPath(file);
    await writeFile(filePath, body);
    await testInfo.attach(file, { path: filePath, contentType: "image/png" });
  }
  return { ratio: result.ratio, size: result.size };
}
