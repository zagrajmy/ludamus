import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// frostfire-con is the panel-lab event: bootstrap_facilitators.py seeds it with
// facilitators of accreditation "none" and nobody honorary.
const DISCOUNTS_URL = "/panel/event/frostfire-con/discounts/";

test.describe("Panel discounts", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
  });

  test("a filter matching nobody keeps the toolbar and offers a way out", async ({
    page,
  }, testInfo) => {
    await page.goto(`${DISCOUNTS_URL}?accreditation=honorary`);

    await expect(page.getByLabel("Accreditation")).toHaveValue("honorary");
    await expect(page.getByText("No facilitators match your filters.")).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    await attachArtifacts(testInfo, {
      name: "discounts-no-match",
      region: page.locator("main"),
      facts: { url: page.url() },
    });

    await page.getByRole("link", { name: "Clear filters" }).click();
    await expect(page).toHaveURL(new RegExp(`${DISCOUNTS_URL}$`));
    await expect(page.getByRole("table")).toBeVisible();
  });

  test("assigning and removing a discount keeps the filter", async ({ page }) => {
    await page.goto(`${DISCOUNTS_URL}?accreditation=none`);

    const row = page
      .getByRole("row")
      .filter({ has: page.getByRole("link", { name: "Assign" }) })
      .first();
    const name = (await row.getByRole("cell").first().innerText()).trim();
    await row.getByRole("link", { name: "Assign" }).click();
    const modal = page.getByRole("dialog", { name: "Assign discount" });
    // NOTE: the browser refuses whole numbers here: the input renders step="0.01"
    // against min="0.01" despite the form asking for step="any".
    await modal.getByLabel("Value").fill("10.01");
    await modal.getByRole("button", { name: "Assign discount" }).click();

    await expect(page.getByText("Discount assigned successfully.")).toBeVisible();
    await expect(page).toHaveURL(/\?accreditation=none$/);

    const assigned = page.getByRole("row").filter({ hasText: name });
    await assigned.getByRole("button", { name: "Remove" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();

    await expect(page.getByText("Discount removed successfully.")).toBeVisible();
    await expect(page).toHaveURL(/\?accreditation=none$/);
  });
});
