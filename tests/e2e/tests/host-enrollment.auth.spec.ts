import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// The superuser presents "Own Table Demo" (bootstrap_data.py), so they host it,
// and they manage no companions and belong to no party.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const openOwnTable = async (page: import("@playwright/test").Page) => {
  await page.goto("/event/facilitator-edit-demo/");
  await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
  const dialog = page.getByRole("dialog", { name: "Own Table Demo" });
  await expect(dialog).toBeVisible();
  return dialog;
};

test("a host with nobody to bring is offered a party, not a seat", async ({ page }, testInfo) => {
  const dialog = await openOwnTable(page);

  await expect(dialog.getByText("You're running this")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("link", { name: "Enroll others…" })).toHaveCount(0);
  await dialog.screenshot({ path: testInfo.outputPath("host-modal.png") });
  await dialog.getByRole("link", { name: "Create a party…" }).click();

  await expect(page.getByRole("dialog", { name: "Create party" })).toBeVisible();
});

test("the group page greys out the host's own row", async ({ page }, testInfo) => {
  const dialog = await openOwnTable(page);
  const sessionId = (await dialog.getAttribute("id"))!.replace("session-", "");

  await page.goto(`/event/facilitator-edit-demo/session/${sessionId}/enrollment/`);

  const ownRow = page.getByRole("listitem").filter({ hasText: "You" }).first();
  await expect(ownRow).toContainText("Runs this session");
  await expect(ownRow.getByRole("checkbox")).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("host-enroll-page.png"), fullPage: true });
});
