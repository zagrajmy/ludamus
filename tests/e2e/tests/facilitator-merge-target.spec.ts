import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { clearFacilitators, savedAnswers, signUp } from "./helpers/facilitators";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Mistvale Meet" (bootstrap_data.py) has no facilitators of its own:
// the walkthrough signs the same person up twice and merges the copies, and
// the setup clears anything an earlier run left behind.
const LIST_URL = "/panel/event/mistvale-meet/facilitators/";
const FIRST = { name: "Wren Adler", shirt: "L", diet: "vegan" };
const TARGET = { name: "Wren Adler (import)", shirt: "M", diet: "halal" };

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

test.describe("Facilitator merge target", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await clearFacilitators(page, LIST_URL);
  });

  test("the answers pre-checked for the merge follow the target the organizer picks", async ({
    page,
  }, testInfo) => {
    await signUp(page, { listUrl: LIST_URL, ...FIRST });
    await signUp(page, { listUrl: LIST_URL, ...TARGET });

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
    await rows.getByRole("link", { name: "Edit" }).click();

    const facts = { offered, merged: await savedAnswers(page) };
    expect(facts.merged).toEqual({
      displayName: TARGET.name,
      shirt: TARGET.shirt,
      diet: TARGET.diet,
    });
    await attachArtifacts(testInfo, {
      name: "facilitator-merge-target",
      region: page.getByRole("main"),
      facts,
    });
  });
});
