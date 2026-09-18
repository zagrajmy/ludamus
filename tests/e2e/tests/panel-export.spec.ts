import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Each organizer list's way out of the browser: the Export tab on proposals and
// facilitators, the accreditation-sheet button on discounts. Runs against the
// frostfire-con panel-lab event, which bootstrap_facilitators.py seeds with
// facilitators, so the discounts list has rows and a toolbar to click.
const EVENT = "frostfire-con";
const PANEL_URL = `/panel/event/${EVENT}`;

const signInAsManager = async (page: Page): Promise<void> => {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
};

const expectOdsDownload = async (
  page: Page,
  part: string,
  trigger: () => Promise<void>,
): Promise<void> => {
  const download = page.waitForEvent("download");
  await trigger();
  expect((await download).suggestedFilename()).toMatch(
    new RegExp(`^${EVENT}-${part}-\\d{4}-\\d{2}-\\d{2}\\.ods$`),
  );
};

test.describe("Panel list exports", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
  });

  test("proposals: the Export tab downloads the ticked columns", async ({ page }) => {
    await page.goto(`${PANEL_URL}/proposals/`);
    await page.getByRole("tab", { name: "Export" }).click();

    await expect(page.getByRole("heading", { name: "Export proposals" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Title" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Scheduled" })).not.toBeChecked();

    await expectOdsDownload(page, "proposals", () =>
      page.getByRole("button", { name: "Download .ods" }).click(),
    );
  });

  test("facilitators: the Export tab downloads the ticked columns", async ({ page }) => {
    await page.goto(`${PANEL_URL}/facilitators/`);
    await page.getByRole("tab", { name: "Export" }).click();

    await expect(page.getByRole("heading", { name: "Export facilitators" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Discount kind" })).not.toBeChecked();

    await expectOdsDownload(page, "facilitators", () =>
      page.getByRole("button", { name: "Download .ods" }).click(),
    );
  });

  test("discounts: the accreditation-sheet button downloads at once", async ({ page }) => {
    await page.goto(`${PANEL_URL}/discounts/`);

    await expectOdsDownload(page, "accreditation", () =>
      page.getByRole("link", { name: "Export accreditation sheet" }).click(),
    );
  });
});
