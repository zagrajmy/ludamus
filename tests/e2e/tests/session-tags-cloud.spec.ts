import { type Locator, type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const overflowCard = (page: Page) =>
  page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Overflow Tags (Design Preview)" }),
  });

const plusCount = (page: Page) => overflowCard(page).getByText(/^\+\d+$/);

const opacityOf = (locator: Locator) =>
  locator.evaluate((element) => getComputedStyle(element).opacity);

test.describe("Session tags cloud", () => {
  test("one +N for the whole cloud, age among the chips, hover shows the rest", async ({
    page,
  }) => {
    await page.goto("/design/");

    const card = overflowCard(page);
    await expect(
      card.getByRole("heading", { name: "Overflow Tags (Design Preview)" }),
    ).toBeVisible();

    await expect(plusCount(page)).toHaveCount(1);
    await expect(plusCount(page)).toHaveText("+9");

    const age = card.getByText("12+", { exact: true });
    await expect(age).toBeVisible();
    const order = await card.innerText();
    expect(order.indexOf("12+")).toBeGreaterThan(-1);
    expect(order.indexOf("12+")).toBeLessThan(order.indexOf("+9"));

    const tip = card.getByRole("tooltip");
    await expect.poll(() => opacityOf(tip)).toBe("0");

    await plusCount(page).hover();
    await expect.poll(() => opacityOf(tip)).toBe("1");
    await expect(tip.getByText("Vampire", { exact: true })).toBeVisible();
    await expect(tip.getByText("gambling", { exact: true })).toBeVisible();
  });
});
