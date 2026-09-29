import { type Page } from "@playwright/test";

import { expect } from "./fixtures";

// NOTE: both merge events (bootstrap_data.py) ask presenters exactly these two
// questions.
export const signUp = async (
  page: Page,
  { listUrl, name, shirt, diet }: { listUrl: string; name: string; shirt: string; diet: string },
): Promise<void> => {
  await page.goto(listUrl);
  await page.getByRole("link", { name: "New Facilitator" }).first().click();
  await page.getByLabel("Display Name").fill(name);
  await page.getByLabel("T-shirt size").fill(shirt);
  await page.getByLabel("Diet").fill(diet);
  await page.getByRole("button", { name: "Create Facilitator" }).click();
  await expect(page.getByText("Facilitator created successfully.")).toBeVisible();
};

export const clearFacilitators = async (page: Page, listUrl: string): Promise<void> => {
  await page.goto(listUrl);
  if (await page.getByText("No facilitators yet.").isHidden()) {
    await page.getByRole("checkbox", { name: "Select all facilitators" }).check();
    await page.getByRole("button", { name: "Delete", exact: true }).first().click();
    await expect(page.getByText("No facilitators yet.")).toBeVisible();
  }
};

export const savedAnswers = async (page: Page) => ({
  displayName: await page.getByRole("main").getByRole("heading", { level: 2 }).innerText(),
  shirt: await page.getByLabel("T-shirt size").inputValue(),
  diet: await page.getByLabel("Diet").inputValue(),
});
