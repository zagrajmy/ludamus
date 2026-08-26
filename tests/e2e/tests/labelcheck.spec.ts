import { expect, test } from "./helpers/fixtures";
test("labelcheck", async ({ page }) => {
  await page.setViewportSize({ height: 812, width: 390 });
  await page.goto("/event/autumn-open/");
  await page.getByRole("button", { exact: true, name: "Filters" }).click();
  await page.waitForTimeout(700);
  const exactClose = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("*")]
      .filter((el) => (el.getAttribute("aria-label") ?? el.textContent?.trim()) === "Close")
      .map((el) => `${el.tagName}#${el.id}`),
  );
  console.log("EXACT-CLOSE " + JSON.stringify(exactClose));
  expect(exactClose).toEqual([]);
});
