import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// Read-only over the `revised-questions` seed (bootstrap_data.py): a proposal
// answering "Legacy question?", which only its former category asks.
const PROPOSALS_URL = "/panel/event/revised-questions/proposals/";
const PROPOSAL = "Revised Proposal";
const QUESTION = "Legacy question?";

test.describe("Proposal orphan answers", () => {
  test.use({ storageState: managerState });

  test("shows an answer outside the category read-only until the category asks it", async ({
    page,
  }) => {
    await page.goto(PROPOSALS_URL);
    await page.getByRole("link", { name: PROPOSAL }).click();
    await page.getByRole("link", { name: "Edit", exact: true }).click();

    const row = page.getByRole("listitem").filter({ hasText: QUESTION });
    const input = page.locator('[name="session_legacy"]');
    await expect(
      page.getByRole("heading", { name: "Answers outside this category" }),
    ).toBeVisible();
    await expect(row.getByText("Old answer")).toBeVisible();
    await expect(row.getByRole("checkbox", { name: `Remove ${QUESTION}` })).not.toBeChecked();
    await expect(input).toHaveCount(0);

    const fields = page.locator("#proposal-session-fields");
    await fields.evaluate((element: HTMLElement) => {
      element.dataset.stale = "1";
    });
    await page.getByLabel("Category").selectOption({ label: "Former Format" });
    await expect(page.locator("#proposal-session-fields[data-stale]")).toHaveCount(0);

    await expect(input).toBeVisible();
    await expect(row).toHaveCount(0);
  });
});
