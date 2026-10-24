import { createHmac } from "node:crypto";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// bootstrap_data.py: a guest's Saturday order on ticket-fair waits in
// Checkout; this spec pays it through a signed webhook, signed out throughout.
const TICKETS_URL = "/event/ticket-fair/tickets/";
const ORDER_URL = "/event/ticket-fair/tickets/orders/e2e-guest/";
const GUEST_EMAIL = "guest-buyer@test.local";
const WEBHOOK_SECRET = process.env.STRIPE_CONNECT_WEBHOOK_SECRET ?? "";

const signed = (body: string): string => {
  const timestamp = Math.floor(Date.now() / 1000);
  const digest = createHmac("sha256", WEBHOOK_SECRET).update(`${timestamp}.${body}`).digest("hex");
  return `t=${timestamp},v1=${digest}`;
};

test.describe.configure({ mode: "serial" });

test.describe("Buying tickets as a guest", () => {
  test("the shop sells without an account", async ({ page }) => {
    await page.goto(TICKETS_URL);

    await expect(page.getByRole("button", { name: "Continue to payment" })).toBeVisible();
    await expect(page.getByText(/No account needed\./)).toBeVisible();
  });

  test("a paid guest order shows its tickets and offers an account", async ({ page }, testInfo) => {
    const body = JSON.stringify({
      id: `evt_e2e_guest_${Date.now()}`,
      object: "event",
      type: "checkout.session.completed",
      account: "acct_e2e_ticket_fair",
      data: {
        object: {
          id: "cs_e2e_guest",
          object: "checkout.session",
          mode: "payment",
          payment_status: "paid",
          payment_intent: "pi_e2e_guest",
          customer_details: { email: GUEST_EMAIL },
        },
      },
    });
    const delivered = await page.request.post("/hooks/stripe/connect", {
      data: body,
      headers: { "Content-Type": "application/json", "Stripe-Signature": signed(body) },
    });
    expect(delivered.status()).toBe(200);
    expect(["paid", "stale"]).toContain((await delivered.json()).outcome);

    await page.goto(ORDER_URL);
    await expect(page.getByRole("heading", { name: "You're going!" })).toBeVisible();
    await expect(page.getByRole("img", { name: /^QR code for ticket / })).toBeVisible();
    const keep = page.getByRole("region", { name: "Keep your tickets safe" });
    await expect(keep.getByText(GUEST_EMAIL)).toBeVisible();
    // Slashes stay unescaped, so analytics redaction finds the reference here too.
    const next = ORDER_URL;
    await expect(keep.getByRole("link", { name: "Create an account" })).toHaveAttribute(
      "href",
      new RegExp(`next=${next}.*screen_hint=signup`),
    );
    await expect(keep.getByRole("link", { name: "Log in" })).toHaveAttribute(
      "href",
      new RegExp(`next=${next}$`),
    );

    await attachArtifacts(testInfo, {
      name: "guest-order",
      region: page.locator("main"),
      facts: { url: page.url(), webhook: await delivered.json() },
    });
  });
});
