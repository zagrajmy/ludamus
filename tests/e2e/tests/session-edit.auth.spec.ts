import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const SEEDED_DESCRIPTION = "A session its presenter can edit from the modal.";

test.describe("Editing a scheduled session from its modal", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

  test("saving an edit closes the modal and the card shows it", async ({ page }) => {
    const edited = `Edited from the modal ${Date.now()}`;
    await page.goto("/event/facilitator-edit-demo/");
    const card = page.locator("[data-session-card]").filter({ hasText: "Own Table Demo" });
    await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
    const dialog = page.getByRole("dialog", { name: "Own Table Demo" });
    await dialog.getByRole("button", { name: "Edit session" }).click();

    try {
      await dialog.getByLabel("Description").fill(edited);
      await dialog.getByRole("button", { name: "Save changes" }).click();

      // No "Saved" state to read and dismiss: the dialog is done and goes.
      await expect(dialog).toBeHidden();
      await expect(page).not.toHaveURL(/[?&]session=/);
      await expect(card).toContainText(edited);

      // The swapped-in card answers the search like the cards booted with the page.
      const search = page.getByRole("textbox", { name: "Search by name or text..." });
      await search.fill("no session is called this");
      await expect(card).toBeHidden();
      await search.fill(edited);
      await expect(card).toBeVisible();
      await search.fill("");
      await attachArtifacts(test.info(), {
        name: "session-edit-saved-card",
        region: card,
        facts: { description: edited },
      });

      // Reopening shows the edit, not the dialog cached before it.
      await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
      await expect(dialog).toContainText(edited);
    } finally {
      await page.goto("/event/facilitator-edit-demo/");
      await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
      await dialog.getByRole("button", { name: "Edit session" }).click();
      await dialog.getByLabel("Description").fill(SEEDED_DESCRIPTION);
      await dialog.getByRole("button", { name: "Save changes" }).click();
      await expect(dialog).toBeHidden();
    }
  });
});

test.describe("Editing a proposal still waiting for acceptance", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-proposal-author.json") });

  test("its author edits it from their pending card", async ({ page }) => {
    const title = `Still Waiting Table ${Date.now()}`;
    await page.goto("/event/facilitator-edit-demo/");
    await page.getByRole("link", { name: "Edit proposal Still Waiting Table" }).click();
    await expect(page.getByRole("heading", { name: "Edit proposal", level: 1 })).toBeVisible();

    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect(page).toHaveURL(/\/event\/facilitator-edit-demo\/$/);
    await expect(page.getByText("Your changes are saved.")).toBeVisible();
    const card = page.locator("[data-session-card]").filter({ hasText: title });
    await expect(card).toBeVisible();
    await attachArtifacts(test.info(), {
      name: "pending-proposal-edited",
      region: card,
      facts: { title },
    });

    // Put the seeded title back, so a rerun finds the card by its name.
    await page.getByRole("link", { name: `Edit proposal ${title}` }).click();
    await page.getByLabel("Title").fill("Still Waiting Table");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Your changes are saved.")).toBeVisible();
  });
});
