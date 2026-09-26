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

  // Messenger and friends fetch the raw HTML and never run the script that
  // opens a ?session= modal, so read the page the way they do: no browser.
  test("unfurls a shared session as that session, not its event", async ({ page, request }) => {
    await page.goto("/event/autumn-open/");
    const href = await page.locator('a[href*="?session="]').first().getAttribute("href");
    const pk = /\?session=(\d+)/.exec(href ?? "")?.[1];
    expect(pk).toBeDefined();
    const shared = `/event/autumn-open/?session=${pk}`;

    // The title a reader sees once the link is opened in a browser.
    await page.goto(shared);
    const title = (await page.locator(`#session-${pk}-title`).innerText()).trim();
    // The session takes the event's place in the title; the sphere tail stays.
    const tail = (await page.title()).replace(/^Autumn Open Playtest /u, "");

    const html = await (await request.get(shared)).text();
    const meta = (key: string): string =>
      new RegExp(`<meta[^>]+(?:property|name)="${key}"[^>]+content="([^"]*)"`, "s")
        .exec(html)?.[1]
        .replaceAll(/\s+/g, " ")
        .trim() ?? "";

    expect(meta("og:title")).toBe(`${title} ${tail}`);
    expect(meta("og:title")).not.toContain("Autumn Open Playtest");
    expect(meta("twitter:title")).toBe(meta("og:title"));
    // Day, time range, room, dot-separated: enough to decide from the preview alone.
    expect(meta("og:description")).toMatch(/^\S+, \d+ \S+ · \d+:\d\d–\d+:\d\d · /u);
    expect(meta("twitter:description")).toBe(meta("og:description"));
    expect(html).toMatch(/<title>\s*Autumn Open Playtest • /);
  });
});
