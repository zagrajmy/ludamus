import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

// The signed-in profile pages whose behavior used to live in inline
// event-handler attributes — see csp-violations.spec.ts for the rest of the
// sweep and why the enforcing header is what this server actually sends.
//
// crowd/user/avatar.html's radios (also converted, to data-action="submit-form")
// aren't covered here: they render only for a user with a provider avatar, and
// the e2e fixtures create local accounts. Its visible "Save" button submits the
// same form, so that page degrades rather than breaking.

test.describe("CSP enforcement doesn't break converted profile handlers", () => {
  test("companion row's inline edit toggle", async ({ page }) => {
    await installCspViolationCollector(page);
    const companionName = `CSP Companion ${Date.now()}`;

    await page.goto("/crowd/profile/parties/");
    await page.getByRole("link", { name: "Add companion", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Add companion" });
    await dialog.getByLabel("Display name").fill(companionName);
    await dialog.getByRole("button", { name: "Add companion", exact: true }).click();
    await expect(page.getByText(companionName, { exact: true })).toBeVisible();

    // Was a pair of inline onclick handlers juggling style.display; now
    // data-action="swap-visibility" through actions.ts. Earlier rows from
    // other specs may exist, so this drives the first row — whichever it is,
    // its edit form has to open.
    await page.getByRole("button", { name: "Edit" }).first().click();

    await expect(page.getByRole("button", { name: "Save changes" }).first()).toBeVisible();
    await assertNoCspViolations(page);
  });
});
