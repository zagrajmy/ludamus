import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";
import { CREW_SPHERE } from "./helpers/urls";

const TICKETS_URL = "/panel/event/ticket-fair/tickets/";
// Crew has no Stripe account connected, so its events can't sell yet.
const UNCONNECTED_TICKETS_URL = `${CREW_SPHERE}/panel/event/crew-open-night/tickets/`;
const crewManagerState = path.join(__dirname, "..", ".auth-state-crew-manager.json");

test.describe("Panel tickets", () => {
  test.use({ storageState: managerState });

  test("shows takings, ticket types and orders", async ({ page }, testInfo) => {
    await page.goto(TICKETS_URL);

    await expect(page.getByRole("heading", { name: "Sales so far", exact: true })).toBeVisible();
    const types = page.getByRole("table").first();
    await expect(types.getByRole("row", { name: /Weekend pass/ })).toContainText("120.00 zł");
    await expect(types.getByRole("row", { name: /Supporter pass/ })).toContainText("1 / 1");
    await expect(page.getByRole("heading", { name: "Orders", exact: true })).toBeVisible();
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
    await expect(page.getByText("Ticket type added.", { exact: true })).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(name) })).toContainText("45.00 zł");
  });
});

test.describe("Panel tickets in a sphere without Stripe", () => {
  test.use({ storageState: crewManagerState });

  test("a manager can connect Stripe from the Tickets page", async ({ page }, testInfo) => {
    await page.goto(UNCONNECTED_TICKETS_URL);

    const payouts = page.getByRole("region", { name: "Connect Stripe to sell tickets" });
    await expect(payouts).toBeVisible();
    await expect(payouts.getByRole("button", { name: "Connect Stripe" })).toBeEnabled();

    await attachArtifacts(testInfo, {
      name: "panel-tickets-connect-stripe",
      region: payouts,
      facts: { url: page.url() },
    });
  });
});
