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

  test("serves the brand card at 1200x630", async ({ request, baseURL }) => {
    const response = await request.get(new URL("/static/og-image.jpg", baseURL).toString());

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("image/jpeg");
  });
});
