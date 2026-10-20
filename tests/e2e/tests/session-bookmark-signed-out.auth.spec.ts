import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

// The toggle only renders for a signed-in viewer, so a 401 means the session
// ended after the page loaded, in another tab or by expiry.
test("a bookmark after the session ended asks to sign in again", async ({ browser }) => {
  const context = await browser.newContext({
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();
  await page.goto(DENSE_EVENT_URL);
  const toggle = page.locator("[data-bookmark-toggle]:visible").first();

  // Signs out without touching the CSRF cookie, the way a logout elsewhere does.
  await context.clearCookies({ name: "sessionid" });
  // The e2e Auth0 tenant is a placeholder, so stop at our own login view.
  await page.route(/\/crowd\/auth0\/do\/login/, (route) =>
    route.fulfill({ body: "<title>Sign in</title>", contentType: "text/html" }),
  );
  const errors: string[] = [];
  // NOTE: Chrome reports the 401 response itself as a console error; only
  // errors the page logs count here.
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      errors.push(message.text());
    }
  });
  await toggle.click();

  await page.waitForURL(/\/crowd\/auth0\/do\/login/);
  const next = new URL(page.url()).searchParams.get("next");
  expect(next).toBe(DENSE_EVENT_URL);
  expect(errors).toEqual([]);
  await context.close();
});
