import { type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";

import { expect, test } from "./helpers/fixtures";

// "Emberfall Moot" (bootstrap_data.py) asks presenters two things, T-shirt size
// and diet, and has no facilitators of its own: the walkthrough signs up the
// same person three times, merges the copies and deletes what is left, and the
// setup clears anything an interrupted run left behind.
const LIST_URL = "/panel/event/emberfall-moot/facilitators/";
const TARGET = "Rowan Ash";
const IMPORTED = "Rowan Ash (import)";
const INITIALS = "R. Ash";

const signUp = async (
  page: Page,
  { name, shirt, diet }: { name: string; shirt: string; diet: string },
): Promise<void> => {
  await page.goto(LIST_URL);
  await page.getByRole("link", { name: "New Facilitator" }).first().click();
  await page.getByLabel("Display Name").fill(name);
  await page.getByLabel("T-shirt size").fill(shirt);
  await page.getByLabel("Diet").fill(diet);
  await page.getByRole("button", { name: "Create Facilitator" }).click();
  await expect(page.getByText("Facilitator created successfully.")).toBeVisible();
};

const detailValue = (page: Page, term: string) =>
  page.getByText(term, { exact: true }).locator("xpath=following-sibling::dd[1]");

test.describe("Facilitator merge", () => {
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

  test("an organizer reconciles three sign-ups into one, and an answer withdrawn meanwhile falls back to the target's", async ({
    page,
  }, testInfo) => {
    await signUp(page, { name: TARGET, shirt: "L", diet: "vegan" });
    await signUp(page, { name: IMPORTED, shirt: "M", diet: "vegan" });
    await signUp(page, { name: INITIALS, shirt: "S", diet: "halal" });

    await page.goto(LIST_URL);
    for (const name of [TARGET, IMPORTED, INITIALS]) {
      await page.getByRole("checkbox", { name: `Select ${name}`, exact: true }).check();
    }
    await page.getByRole("button", { name: "Merge selected" }).click();
    await expect(page.getByRole("heading", { name: "Selected for merge (3)" })).toBeVisible();
    await page.getByRole("button", { name: "Review and merge" }).click();

    await page
      .getByRole("group", { name: "Merge target" })
      .getByLabel(TARGET, { exact: true })
      .check();
    await page
      .getByRole("group", { name: "Display Name" })
      .getByLabel(TARGET, { exact: true })
      .check();
    // The two sign-ups that agree on a diet are offered as one answer.
    const diet = page.getByRole("group", { name: "Diet" });
    await expect(diet.getByRole("radio")).toHaveCount(2);
    await expect(diet.getByText(`${TARGET}, ${IMPORTED}`)).toBeVisible();
    await diet.getByRole("radio", { name: /^vegan ·/ }).check();
    await page
      .getByRole("group", { name: "T-shirt size" })
      .getByRole("radio", { name: /^S ·/ })
      .check();

    // Meanwhile, in another tab, the S answer is withdrawn.
    const otherTab = await page.context().newPage();
    await otherTab.goto(LIST_URL);
    await otherTab
      .getByRole("row")
      .filter({ hasText: INITIALS })
      .getByRole("link", { name: "Edit" })
      .click();
    await otherTab.getByLabel("T-shirt size").fill("");
    await otherTab.getByRole("button", { name: /Save/ }).click();
    await expect(otherTab.getByText("Facilitator updated successfully.")).toBeVisible();
    await otherTab.close();

    await page.getByRole("button", { name: "Merge", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Merge" }).click();
    await expect(page.getByText("Facilitators merged successfully.")).toBeVisible();

    await page.reload();
    const rows = page.getByRole("table").getByRole("row").filter({ hasText: "Ash" });
    await expect(rows).toHaveCount(1);
    await rows.getByRole("link", { name: TARGET, exact: true }).click();
    await expect(page.getByRole("heading", { name: TARGET })).toBeVisible();

    const facts = {
      facilitatorsLeft: 1,
      displayName: (await detailValue(page, "Display Name").innerText()).trim(),
      shirt: (await detailValue(page, "T-shirt size").innerText()).trim(),
      diet: (await detailValue(page, "Diet").innerText()).trim(),
    };
    expect(facts).toEqual({ facilitatorsLeft: 1, displayName: TARGET, shirt: "L", diet: "vegan" });
    const screenshotPath = testInfo.outputPath("merged-facilitator.png");
    await page.getByRole("main").screenshot({ path: screenshotPath });
    await testInfo.attach("merged-facilitator.png", {
      path: screenshotPath,
      contentType: "image/png",
    });
    const factsPath = testInfo.outputPath("merged-facilitator.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("merged-facilitator.json", {
      path: factsPath,
      contentType: "application/json",
    });
  });
});
