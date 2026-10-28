import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

for (const anonymous of [true, false]) {
  test.describe(
    anonymous ? "Anonymous uncategorized proposal" : "Signed-in uncategorized proposal",
    () => {
      test.use({
        storageState: anonymous
          ? { cookies: [], origins: [] }
          : path.join(__dirname, "..", ".auth-state.json"),
      });

      test("submits without category setup, including participant validation", async ({ page }) => {
        const title = `No category ${anonymous ? "anon" : "member"} ${Date.now()}`;
        await page.goto("/event/lone-table/session/propose/");
        const wizard = page.locator('[id="wizard-content"]');

        if (anonymous) {
          await expect(wizard.getByRole("heading", { name: "Your Information" })).toBeVisible();
          await page.getByLabel(/contact email/i).fill("uncategorized@example.com");
          await page.getByRole("button", { name: /Continue/ }).click();
        }
        await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
        await expect(wizard.getByText("Category", { exact: true })).toHaveCount(0);
        await expect(wizard.getByText("Time slots", { exact: true })).toHaveCount(0);
        await page.getByLabel(/title/i).fill(title);
        await page
          .getByLabel(/about this session/i)
          .fill("A proposal that needs no organizer configuration.");
        await page.getByLabel(/presenter name/i).fill("Independent Host");
        await page.getByLabel(/seats/i).fill("-1");
        await page.getByRole("button", { name: /Continue/ }).click();
        await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
        await page.getByLabel(/seats/i).fill("");
        await attachArtifacts(test.info(), {
          name: `uncategorized-details-${anonymous ? "anon" : "member"}`,
          region: wizard,
          facts: { title, anonymous, category: null },
        });
        await page.getByRole("button", { name: /Continue/ }).click();

        await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
        await expect(wizard.getByRole("heading", { name: "Category", exact: true })).toHaveCount(0);
        await page.setViewportSize({ width: 390, height: 844 });
        await attachArtifacts(test.info(), {
          name: `uncategorized-review-${anonymous ? "anon" : "member"}`,
          region: wizard,
          facts: { title, anonymous, category: null },
        });
        await page.getByRole("button", { name: "Submit Proposal" }).click();
        await expect(page).toHaveURL(/\/event\/lone-table\/$/);
        await expect(
          page.getByText(`Session proposal '${title}' submitted successfully!`),
        ).toBeVisible();
      });
    },
  );
}
