import { writeFile } from "node:fs/promises";

import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

declare global {
  interface Window {
    __xss?: number;
  }
}

// bootstrap_data.py seeds "Hostile Markdown Demo" with a description mixing a
// <script>, inline handlers, a javascript: link and an iframe with ordinary
// markdown. The enforcing CSP would stop most of it from running anyway, so
// the proof is the DOM: none of the hostile markup may reach it at all.
test.describe("Session description markdown", () => {
  test("renders benign markdown and strips scripts, handlers and javascript: links", async ({
    page,
  }, testInfo) => {
    const dialogs: string[] = [];
    page.on("dialog", async (dialog) => {
      dialogs.push(dialog.message());
      await dialog.dismiss();
    });
    await installCspViolationCollector(page);

    await page.goto("/event/markdown-sanitising/");
    await page.getByRole("link", { name: "Open details for Hostile Markdown Demo" }).press("Enter");

    const modal = page.getByRole("dialog", { name: "Hostile Markdown Demo" });
    await expect(modal).toBeVisible();
    const description = modal.locator("[data-session-description]");

    await expect(description.locator("strong", { hasText: "bold claim" })).toBeVisible();
    await expect(description.getByRole("link", { name: "safe link" })).toHaveAttribute(
      "href",
      "https://example.com/rules",
    );
    await expect(description.getByText("click me")).toBeVisible();
    await expect(description.getByText("hover target")).toBeVisible();

    await expect(description.locator("script, img, iframe")).toHaveCount(0);
    await expect(description.locator('a[href^="javascript:" i]')).toHaveCount(0);
    const handlerAttributes = await description.evaluate((root) =>
      [root, ...root.querySelectorAll("*")].flatMap((element) =>
        element
          .getAttributeNames()
          .filter((name) => name.toLowerCase().startsWith("on"))
          .map((name) => `${element.tagName.toLowerCase()}[${name}]`),
      ),
    );
    expect(handlerAttributes).toEqual([]);

    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    expect(dialogs).toEqual([]);
    await assertNoCspViolations(page);

    // Written to the test's output dir as well as attached, so a passing run
    // leaves the rendered result on disk next to the HTML report's copy.
    const screenshotPath = testInfo.outputPath("sanitised-description.png");
    await description.screenshot({ path: screenshotPath });
    await testInfo.attach("sanitised-description.png", {
      path: screenshotPath,
      contentType: "image/png",
    });
    const htmlPath = testInfo.outputPath("sanitised-description.html");
    await writeFile(htmlPath, await description.innerHTML());
    await testInfo.attach("sanitised-description.html", {
      path: htmlPath,
      contentType: "text/html",
    });
  });
});
