import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

// The toggle only renders for a signed-in viewer, so a 401 means the session
// ended after the page loaded, in another tab or by expiry.
test("a bookmark after the session ended asks to sign in again", async ({ context, page }) => {
  await page.goto(DENSE_EVENT_URL);
  const toggle = page.getByRole("button", { name: "Bookmark session" }).first();
  const pressed = await toggle.getAttribute("aria-pressed");

  // Signs out without touching the CSRF cookie, the way a logout elsewhere does.
  await context.clearCookies({ name: "sessionid" });
  // The e2e Auth0 tenant is a placeholder, so the sign-in navigation is
  // aborted: Chrome then keeps this page, and with it the star and the
  // client coverage of the branch. What the login view does with `next` is
  // test_login_action.py's.
  await page.route(/\/crowd\/auth\/do\/login/, (route) => route.abort("aborted"));
  const signIn = page.waitForRequest(/\/crowd\/auth\/do\/login/);
  const errors: string[] = [];
  // NOTE: Chrome reports the 401 response itself as a console error; only
  // errors the page logs count here.
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      errors.push(message.text());
    }
  });
  await toggle.click();

  const next = new URL((await signIn).url()).searchParams.get("next");
  expect(next).toBe(DENSE_EVENT_URL);
  await expect(toggle).toHaveAttribute("aria-pressed", pressed ?? "false");
  expect(errors).toEqual([]);
});
