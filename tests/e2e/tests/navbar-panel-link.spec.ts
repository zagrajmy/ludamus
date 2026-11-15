import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// The account menu links to the backoffice panel only for someone with panel
// access to the current sphere. e2e-tester is a plain member of the root
// sphere; e2e-manager manages it.

const memberState = path.join(__dirname, "..", ".auth-state.json");

test.describe("as the sphere's manager", () => {
  test.use({ storageState: managerState });

  test("the account menu links to the panel", async ({ page }, testInfo) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Account menu" }).click();

    const panel = page.getByRole("link", { name: "Panel", exact: true });
    await expect(panel).toBeVisible();
    await attachArtifacts(testInfo, {
      name: "account-menu-panel-link",
      region: panel,
      facts: { user: "e2e-manager", link: "Panel" },
    });

    await panel.click();
    await expect(page).toHaveURL(/\/panel\//);
  });
});

test.describe("as a plain member", () => {
  test.use({ storageState: memberState });

  test("the account menu has no panel link", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Account menu" }).click();

    await expect(page.getByRole("link", { name: "Your dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Panel", exact: true })).toHaveCount(0);
  });
});
