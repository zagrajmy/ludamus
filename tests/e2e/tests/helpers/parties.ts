import { type Page } from "@playwright/test";

import { expect } from "./fixtures";

export type Party = { name: string; url: string };

// NOTE: a name unique to the run, so a party a killed run left never collides.
export const foundParty = async (page: Page, prefix: string): Promise<Party> => {
  const name = `${prefix} ${Date.now()}`;
  await page.goto("/crowd/profile/parties/");
  await page.getByRole("link", { name: "Create party", exact: true }).click();
  const createDialog = page.getByRole("dialog", { name: "Create party" });
  await createDialog.getByLabel("Party name").fill(name);
  await createDialog.getByRole("button", { name: "Create party", exact: true }).click();
  await expect(page).toHaveURL(/\/crowd\/profile\/parties\/\d+\/$/);
  return { name, url: page.url() };
};

export const disbandParty = async (page: Page, { name, url }: Party): Promise<void> => {
  await page.goto(url);
  await page.getByRole("button", { name: "Delete party" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete party" }).click();
  await expect(page.getByText("Party deleted.")).toBeVisible();
  await expect(page.getByText(name)).toHaveCount(0);
};
