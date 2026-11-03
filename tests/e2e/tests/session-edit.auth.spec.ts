import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const SEEDED_DESCRIPTION = "A session its presenter can edit from the modal.";

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
