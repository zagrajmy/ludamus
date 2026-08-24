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

  test("upgrades the combobox and filters its options", async ({ page }) => {
    await page.goto("/design/");

    const combobox = page.getByRole("combobox", { name: "Fruit" });
    // The upgrade swaps the control: the select steps aside for the input.
    await expect(combobox).toHaveAttribute("role", "combobox");
    await expect(page.locator("#t-combobox")).toBeHidden();

    await combobox.fill("ap");
    await expect(page.getByRole("listbox", { name: "Fruit" }).getByRole("option")).toHaveText([
      "Apple",
      "Apricot",
    ]);

    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    await combobox.press("Enter");
    await expect(combobox).toHaveValue("Apricot");
    // The select is still the value — a form would post this.
    await expect(page.locator("#t-combobox")).toHaveValue("apricot");
  });

  test("keeps the native select when scripts do not run", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto("/design/");

    // The markup ships a working select; the shell only appears once the
    // script has something to upgrade it to.
    await expect(page.locator("#t-combobox")).toBeVisible();
    await expect(page.locator("#t-combobox-input")).toBeHidden();

    await context.close();
  });
});
