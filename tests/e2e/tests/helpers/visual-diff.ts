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
      const pixels = (img: HTMLImageElement) => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(img, 0, 0);
        return ctx.getImageData(0, 0, width, height).data;
      };
      const pa = pixels(imgA);
      const pb = pixels(imgB);
      const out = new ImageData(width, height);
      let differing = 0;
      for (let i = 0; i < pa.length; i += 4) {
        const delta =
          Math.abs(pa[i] - pb[i]) +
          Math.abs(pa[i + 1] - pb[i + 1]) +
          Math.abs(pa[i + 2] - pb[i + 2]);
        const hit = delta > 48;
        if (hit) differing += 1;
        out.data[i] = hit ? 230 : 180 + pa[i] * 0.25;
        out.data[i + 1] = hit ? 30 : 180 + pa[i + 1] * 0.25;
        out.data[i + 2] = hit ? 30 : 180 + pa[i + 2] * 0.25;
        out.data[i + 3] = 255;
      }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d")!.putImageData(out, 0, 0);
      return {
        ratio: differing / (width * height),
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
