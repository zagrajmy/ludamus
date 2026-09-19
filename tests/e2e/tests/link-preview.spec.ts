import { expect, test } from "./helpers/fixtures";

/**
 * What a shared link unfurls as. Crawlers read the rendered head, and they
 * fetch og:image by URL, so both have to be absolute and correct in the markup.
 */
test.describe("Link preview metadata", () => {
  test("points at the absolute brand card by default", async ({ page, baseURL }) => {
    await page.goto("/");

    const expected = new URL("/static/og-image.jpg", baseURL).toString();
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", expected);
    await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute("content", expected);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      "content",
      "summary_large_image",
    );
  });

  test("serves the brand card at 1200x630", async ({ page, request, baseURL }) => {
    const url = new URL("/static/og-image.jpg", baseURL).toString();
    const response = await request.get(url);

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("image/jpeg");

    // Crawlers reject an unfurl whose image is not the ratio they expect, so
    // decode it rather than trusting the file the build task left behind.
    await page.goto("/");
    const size = await page.evaluate(async (source) => {
      const image = new Image();
      image.src = source;
      await image.decode();
      return { height: image.naturalHeight, width: image.naturalWidth };
    }, url);

    expect(size).toEqual({ height: 630, width: 1200 });
  });
});
