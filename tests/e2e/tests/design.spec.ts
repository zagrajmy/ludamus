import { expect, test } from "./helpers/fixtures";

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

    const playground = page.getByRole("group", { name: "Toast playground" });
    await playground.getByRole("button", { name: "Show success" }).click();
    await playground.getByRole("button", { name: "Show sticky error" }).click();

    const toasts = page.getByRole("region", { name: "Notifications" }).locator("[data-flash]");
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

  test("frames the link-preview card with the lockup centred", async ({ page }) => {
    await page.goto("/design/");

    const card = page.frameLocator('iframe[src*="og-card"]');
    await expect(card.locator(".card__lockup")).toBeVisible();
    // The lockup is the whole card, so an off-centre viewBox shows up as a
    // lopsided margin rather than as anything failing to render.
    const offset = await card.locator(".card__lockup").evaluate((svg) => {
      const lockup = svg.getBoundingClientRect();
      const frame = document.querySelector(".card").getBoundingClientRect();
      return {
        x: Math.abs(lockup.left - frame.left - (frame.right - lockup.right)),
        y: Math.abs(lockup.top - frame.top - (frame.bottom - lockup.bottom)),
      };
    });
    expect(offset.x).toBeLessThan(1);
    expect(offset.y).toBeLessThan(1);
  });
});
