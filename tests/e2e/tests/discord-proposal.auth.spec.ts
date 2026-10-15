import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// The pub-night category asks only for a Discord handle (bootstrap_data.py).
const proposeUrl = "/event/pub-night/session/propose/";

test.describe("Discord handle on the proposal wizard", () => {
  test("asks a proposer whose account has no handle", async ({ page }) => {
    await page.goto(proposeUrl);

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Your Information" })).toBeVisible();
    await expect(page.getByLabel("Identyfikator discord")).toHaveValue("");
  });

  test.describe("account with a handle", () => {
    test.use({ storageState: path.join(__dirname, "..", ".auth-state-discord.json") });

    test("skips the step and carries email and handle to the review", async ({ page }) => {
      await page.goto(proposeUrl);

      const wizard = page.locator('[id="wizard-content"]');
      await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
      await expect(page.getByText("Your info")).toHaveCount(0);
      // Details is now the first step: nothing to go back to.
      await expect(wizard.getByRole("button", { name: /Back/ })).toHaveCount(0);

      await page.getByLabel(/title/i).fill("Pub Crawl of Cthulhu");
      await page.getByLabel(/description/i).fill("Investigators, pints and unspeakable things.");
      await page.getByLabel(/max participants/i).fill("4");
      await page.getByRole("button", { name: /Continue/ }).click();

      await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
      await expect(wizard.getByText("e2e-discord@test.local")).toBeVisible();
      await expect(wizard.getByText("e2e_dragon")).toBeVisible();
      await attachArtifacts(test.info(), {
        name: "discord-review",
        region: wizard,
        facts: { email: "e2e-discord@test.local", discord: "e2e_dragon" },
      });

      await page.getByRole("button", { name: "Submit Proposal" }).click();
      await expect(page.getByText("Pub Crawl of Cthulhu")).toBeVisible();
    });
  });
});
