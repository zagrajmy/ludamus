import { type Locator } from "@playwright/test";

import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// Read-only over the `harbour-days` seed (bootstrap_confirmations.py): an
// accepted, placed session by Ada McCall, and her on-hold one beside it.
const EVENT_URL = "/panel/event/harbour-days";
const PLACED = "Dragons of the Harbour";
const ON_HOLD = "Maybe: Harbour Larp";

function badge(scope: Locator, label: string) {
  return scope.getByText(label, { exact: true });
}

test.describe("Proposal status badge", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
  });

  test("a placed session reads Scheduled on every panel page", async ({ page }) => {
    await page.goto(`${EVENT_URL}/proposals/?status=all`);
    const row = page.getByRole("row").filter({ hasText: PLACED });
    await expect(badge(row, "Scheduled")).toBeVisible();

    await row.getByRole("link", { name: PLACED }).click();
    await expect(page.getByRole("heading", { name: PLACED })).toBeVisible();
    await expect(badge(page.locator("main"), "Scheduled")).toBeVisible();

    await page.goto(`${EVENT_URL}/facilitators/ada-mccall/`);
    const item = page.getByRole("listitem").filter({ hasText: PLACED });
    await expect(badge(item, "Scheduled")).toBeVisible();
    await expect(badge(item, "Accepted")).toHaveCount(0);

    await item.locator("xpath=ancestor::ul[1]").screenshot({
      path: "test-results/proposal-status-badge-facilitator.png",
    });
  });

  test("on hold looks the same on the list and the confirmations card", async ({ page }) => {
    await page.goto(`${EVENT_URL}/proposals/?status=all`);
    const row = page.getByRole("row").filter({ hasText: ON_HOLD });
    const listClass = await badge(row, "On hold").getAttribute("class");

    await page.goto(`${EVENT_URL}/timetable/confirmations/`);
    await page.getByRole("link", { name: "Main Programme" }).click();
    const card = page
      .locator("details")
      .filter({ has: page.getByText("Ada McCall", { exact: true }) });
    if ((await card.getAttribute("open")) === null) {
      await card.locator("summary").click();
    }
    await expect(badge(card, "On hold")).toHaveAttribute("class", listClass ?? "");
    await card.screenshot({ path: "test-results/proposal-status-badge-confirmations.png" });
  });
});
