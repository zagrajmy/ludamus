import { expect, test } from "@playwright/test";

test.describe("Design system page", () => {
  test("renders design showcase with component sections", async ({ page }) => {
    await page.goto("/design/");

    // Page should load (design.html extends base)
    await expect(page).toHaveTitle(/tessera/i);

    // Should contain component examples — buttons, cards, alerts, etc.
    await expect(page.getByRole("button").first()).toBeVisible();

    await page.screenshot({
      path: "test-results/design-page.png",
      fullPage: true,
    });
  });

  test("lets people exercise toast stacking and dismissal", async ({ page }) => {
    await page.goto("/design/");

    const playground = page.locator("[data-flash-demo]");
    await playground.getByRole("button", { name: "Show success" }).click();
    await playground.getByRole("button", { name: "Show sticky error" }).click();

    const toasts = page.locator(".flash-region [data-flash]");
    await expect(toasts).toHaveCount(2);
    await expect(toasts.first()).toHaveAttribute("data-flash-mounted", "true");
    await expect
      .poll(() =>
        toasts.evaluateAll((elements) => {
          const [front, back] = elements.map((element) => element.getBoundingClientRect());
          return back.top - front.top < front.height;
        }),
      )
      .toBe(true);

    await playground.getByRole("button", { name: "Dismiss all" }).click();
    await expect(toasts).toHaveCount(0);
  });
});
