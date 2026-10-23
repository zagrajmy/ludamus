import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

const TICKETS_URL = "/panel/event/ticket-fair/tickets/";

test.describe("Panel tickets", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
  });

  test("shows takings, ticket types and orders", async ({ page }, testInfo) => {
    await page.goto(TICKETS_URL);

    await expect(page.getByRole("heading", { name: "Sales so far" })).toBeVisible();
    const types = page.getByRole("table").first();
    await expect(types.getByRole("row", { name: /Weekend pass/ })).toContainText("120.00 zł");
    await expect(types.getByRole("row", { name: /Supporter pass/ })).toContainText("1 / 1");
    await expect(page.getByRole("heading", { name: "Orders" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Refund order" }).first()).toBeVisible();

    await attachArtifacts(testInfo, {
      name: "panel-tickets",
      region: page.locator("main"),
      facts: { url: page.url() },
    });
  });

  test("adding a ticket type puts it on the list", async ({ page }) => {
    const name = `Sunday only ${Date.now()}`;
    await page.goto(TICKETS_URL);
    await page.getByRole("link", { name: "Add ticket type" }).first().click();

    await page.getByLabel("Name").fill(name);
    await page.getByLabel("Price (zł)").fill("45");
    await page.getByLabel("Tickets available").fill("80");
    await page.getByRole("button", { name: "Save ticket type" }).click();

    await expect(page).toHaveURL(TICKETS_URL);
    await expect(page.getByText("Ticket type added.")).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(name) })).toContainText("45.00 zł");
  });
});
