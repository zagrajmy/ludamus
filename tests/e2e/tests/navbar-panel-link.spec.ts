import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// The account menu links to the backoffice panel only for someone with panel
// access to the current sphere. e2e-tester is a plain member of the root
// sphere; e2e-manager manages it. The menu opens from the keyboard: it also
// opens on hover, so a pointer click can land on a menu that is already open
// and toggle it shut.

const memberState = path.join(__dirname, "..", ".auth-state.json");

const openAccountMenu = async (page: Page) => {
  const trigger = page.getByRole("button", { name: "Account menu" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
};

test.describe("as the sphere's manager", () => {
  test.use({ storageState: managerState });

  test("the account menu links to the panel", async ({ page }, testInfo) => {
    await page.goto("/");
    await openAccountMenu(page);

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
    await openAccountMenu(page);

    await expect(page.getByRole("link", { name: "Your dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Panel", exact: true })).toHaveCount(0);
  });
});
