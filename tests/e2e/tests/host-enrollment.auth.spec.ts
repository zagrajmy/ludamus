import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// The superuser presents "Own Table Demo" (bootstrap_data.py), so they host it.
test("a host is offered no seat at their own table", async ({ browser }, testInfo) => {
  const context = await browser.newContext({
    storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  });
  const page = await context.newPage();

  await page.goto("/event/facilitator-edit-demo/");
  await page.getByRole("link", { name: "Open details for Own Table Demo" }).press("Enter");
  const dialog = page.getByRole("dialog", { name: "Own Table Demo" });

  await expect(dialog.getByText("You're running this")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
  await dialog.getByRole("link", { name: "Enroll others…" }).click();

  const ownRow = page.getByRole("listitem").filter({ hasText: "You" }).first();
  await expect(ownRow).toContainText("Runs this session");
  await expect(ownRow.getByRole("checkbox")).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("host-enroll-page.png"), fullPage: true });

  await context.close();
});
