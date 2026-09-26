import { type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";

import { expect, test } from "./helpers/fixtures";

// NOTE: "Mistvale Meet" (bootstrap_data.py) asks presenters their T-shirt size and
// diet, and has no facilitators of its own: the walkthrough signs the same
// person up twice and merges the copies, and the setup clears anything an
// earlier run left behind.
const LIST_URL = "/panel/event/mistvale-meet/facilitators/";
const FIRST = { name: "Wren Adler", shirt: "L", diet: "vegan" };
const TARGET = { name: "Wren Adler (import)", shirt: "M", diet: "halal" };

const signUp = async (page: Page, { name, shirt, diet }: typeof FIRST): Promise<void> => {
  await page.goto(LIST_URL);
  await page.getByRole("link", { name: "New Facilitator" }).first().click();
  await page.getByLabel("Display Name").fill(name);
  await page.getByLabel("T-shirt size").fill(shirt);
  await page.getByLabel("Diet").fill(diet);
  await page.getByRole("button", { name: "Create Facilitator" }).click();
  await expect(page.getByText("Facilitator created successfully.")).toBeVisible();
};

const group = (page: Page, name: string) => page.getByRole("group", { name });

// NOTE: a choice reads as its answer, then " · " and whose answer it is.
const checkedAnswer = async (page: Page, name: string) =>
  (
    await group(page, name)
      .locator("label", { has: page.locator(":checked") })
      .innerText()
  )
    .split("·")[0]
    ?.trim();

const checkedAnswers = async (page: Page) => ({
  target: await checkedAnswer(page, "Merge target"),
  displayName: await checkedAnswer(page, "Display Name"),
  shirt: await checkedAnswer(page, "T-shirt size"),
  diet: await checkedAnswer(page, "Diet"),
});

const detailValue = (page: Page, term: string) =>
  page.getByText(term, { exact: true }).locator("xpath=following-sibling::dd[1]");

test.describe("Facilitator merge target", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();

    await page.goto(LIST_URL);
    if (await page.getByText("No facilitators yet.").isHidden()) {
      await page.getByRole("checkbox", { name: "Select all facilitators" }).check();
      await page.getByRole("button", { name: "Delete", exact: true }).first().click();
      await expect(page.getByText("No facilitators yet.")).toBeVisible();
    }
  });

  test("the answers pre-checked for the merge follow the target the organizer picks", async ({
    page,
  }, testInfo) => {
    await signUp(page, FIRST);
    await signUp(page, TARGET);

    await page.goto(LIST_URL);
    for (const { name } of [FIRST, TARGET]) {
      await page.getByRole("checkbox", { name: `Select ${name}`, exact: true }).check();
    }
    await page.getByRole("button", { name: "Merge selected" }).click();
    await page.getByRole("button", { name: "Review and merge" }).click();

    const targets = group(page, "Merge target").getByRole("radio");
    await expect(targets.first()).toBeChecked();
    await expect(group(page, "Display Name").getByLabel(FIRST.name, { exact: true })).toBeChecked();

    await group(page, "Merge target").getByLabel(TARGET.name, { exact: true }).check();
    await expect(
      group(page, "Display Name").getByLabel(TARGET.name, { exact: true }),
    ).toBeChecked();
    await expect(
      group(page, "T-shirt size").getByRole("radio", { name: new RegExp(`^${TARGET.shirt} ·`) }),
    ).toBeChecked();
    await expect(
      group(page, "Diet").getByRole("radio", { name: new RegExp(`^${TARGET.diet} ·`) }),
    ).toBeChecked();
    const offered = await checkedAnswers(page);

    await page.reload();
    await expect(
      group(page, "Merge target").getByLabel(TARGET.name, { exact: true }),
    ).toBeChecked();
    expect(await checkedAnswers(page)).toEqual(offered);

    await page.getByRole("button", { name: "Merge", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Merge" }).click();
    await expect(page.getByText("Facilitators merged successfully.")).toBeVisible();

    await page.reload();
    const rows = page.getByRole("table").getByRole("row").filter({ hasText: "Wren Adler" });
    await expect(rows).toHaveCount(1);
    await rows.getByRole("link", { name: TARGET.name, exact: true }).click();
    await expect(page.getByRole("heading", { name: TARGET.name })).toBeVisible();

    const facts = {
      offered,
      merged: {
        displayName: (await detailValue(page, "Display Name").innerText()).trim(),
        shirt: (await detailValue(page, "T-shirt size").innerText()).trim(),
        diet: (await detailValue(page, "Diet").innerText()).trim(),
      },
    };
    expect(facts.merged).toEqual({
      displayName: TARGET.name,
      shirt: TARGET.shirt,
      diet: TARGET.diet,
    });
    const screenshotPath = testInfo.outputPath("facilitator-merge-target.png");
    await page.getByRole("main").screenshot({ path: screenshotPath });
    await testInfo.attach("facilitator-merge-target.png", {
      path: screenshotPath,
      contentType: "image/png",
    });
    const factsPath = testInfo.outputPath("facilitator-merge-target.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("facilitator-merge-target.json", {
      path: factsPath,
      contentType: "application/json",
    });
  });
});
