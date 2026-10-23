import { createHmac } from "node:crypto";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// bootstrap_data.py: ticket-fair sells four ticket types on a connected Stripe
// account; the tester holds a paid order and one still in Checkout.
const EVENT_URL = "/event/ticket-fair/";
const TICKETS_URL = "/event/ticket-fair/tickets/";
const WEBHOOK_SECRET = process.env.STRIPE_CONNECT_WEBHOOK_SECRET ?? "";

const signed = (body: string): string => {
  const timestamp = Math.floor(Date.now() / 1000);
  const digest = createHmac("sha256", WEBHOOK_SECRET).update(`${timestamp}.${body}`).digest("hex");
  return `t=${timestamp},v1=${digest}`;
};

test.describe("Ticket sales", () => {
  test("the event page leads to the ticket shop", async ({ page }, testInfo) => {
    await page.goto(EVENT_URL);
    await page.getByRole("link", { name: "Buy tickets" }).click();

    await expect(page).toHaveURL(TICKETS_URL);
    await expect(page.getByRole("heading", { name: "Tickets", level: 1 })).toBeVisible();
    await expect(page.getByText("You have 2 tickets for this event.")).toBeVisible();
    const weekend = page.getByRole("listitem").filter({ hasText: "Weekend pass" });
    await expect(weekend.getByText("120.00 zł")).toBeVisible();
    await expect(weekend.getByRole("spinbutton", { name: "How many: Weekend pass" })).toBeVisible();
    const supporter = page.getByRole("listitem").filter({ hasText: "Supporter pass" });
    await expect(supporter.getByText("Sold out")).toBeVisible();
    await expect(supporter.getByRole("spinbutton")).toHaveCount(0);
    const later = page.getByRole("listitem").filter({ hasText: "Last-minute day pass" });
    await expect(later.getByText(/On sale from/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue to payment" })).toBeVisible();

    await attachArtifacts(testInfo, {
      name: "ticket-shop",
      region: page.locator("main"),
      facts: { url: page.url() },
    });
  });

  test("a paid checkout turns into tickets the buyer can show", async ({ page }, testInfo) => {
    const body = JSON.stringify({
      id: `evt_e2e_${testInfo.project.name}_${Date.now()}`,
      object: "event",
      type: "checkout.session.completed",
      account: "acct_e2e_ticket_fair",
      data: {
        object: {
          id: "cs_e2e_pending",
          object: "checkout.session",
          mode: "payment",
          payment_status: "paid",
          payment_intent: "pi_e2e_pending",
        },
      },
    });

    const delivered = await page.request.post("/hooks/stripe/connect/", {
      data: body,
      headers: { "Content-Type": "application/json", "Stripe-Signature": signed(body) },
    });
    expect(delivered.status()).toBe(200);
    expect(["paid", "stale"]).toContain((await delivered.json()).outcome);

    await page.goto("/crowd/profile/tickets/");
    await expect(page.getByRole("tab", { name: /Tickets/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("heading", { name: "Ticket Fair" })).toBeVisible();
    await expect(page.getByText("WKND2E2EAA")).toBeVisible();
    await expect(page.getByRole("img", { name: "QR code for ticket WKND2E2EAA" })).toBeVisible();
    // The order the webhook paid now holds a Saturday ticket too.
    await expect(page.getByText("Saturday only")).toBeVisible();

    await attachArtifacts(testInfo, {
      name: "my-tickets",
      region: page.locator("main"),
      facts: { url: page.url(), webhook: await delivered.json() },
    });
  });

  test("a forged webhook is refused", async ({ page }) => {
    const body = JSON.stringify({ id: "evt_forged", type: "checkout.session.completed" });

    const response = await page.request.post("/hooks/stripe/connect/", {
      data: body,
      headers: { "Content-Type": "application/json", "Stripe-Signature": "t=1,v1=00" },
    });

    expect(response.status()).toBe(400);
  });
});
