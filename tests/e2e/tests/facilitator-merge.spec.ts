import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { clearFacilitators, savedAnswers, signUp } from "./helpers/facilitators";
import { expect, test } from "./helpers/fixtures";

// NOTE: "Emberfall Moot" (bootstrap_data.py) has no facilitators of its own:
// the walkthrough signs up the same person three times and merges the copies,
// and the setup clears anything an earlier run left behind.
const LIST_URL = "/panel/event/emberfall-moot/facilitators/";
const TARGET = "Rowan Ash";
const IMPORTED = "Rowan Ash (import)";
const INITIALS = "R. Ash";

test.describe("Facilitator merge", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await clearFacilitators(page, LIST_URL);
  });

  test("an organizer reconciles three sign-ups into one, and an answer withdrawn meanwhile falls back to the target's", async ({
    page,
  }, testInfo) => {
    await signUp(page, { listUrl: LIST_URL, name: TARGET, shirt: "L", diet: "vegan" });
    await signUp(page, { listUrl: LIST_URL, name: IMPORTED, shirt: "M", diet: "vegan" });
    await signUp(page, { listUrl: LIST_URL, name: INITIALS, shirt: "S", diet: "halal" });

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
    await test.step("the two sign-ups that agree on a diet are offered as one answer", async () => {
      const diet = page.getByRole("group", { name: "Diet" });
      await expect(diet.getByRole("radio")).toHaveCount(2);
      await expect(diet.getByText(`${TARGET}, ${IMPORTED}`)).toBeVisible();
      await diet.getByRole("radio", { name: /^vegan ·/ }).check();
    });
    await page
      .getByRole("group", { name: "T-shirt size" })
      .getByRole("radio", { name: /^S ·/ })
      .check();

    await test.step("another tab withdraws the S answer before the merge is sent", async () => {
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
    });

    await page.getByRole("button", { name: "Merge", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Merge" }).click();
    await expect(page.getByText("Facilitators merged successfully.")).toBeVisible();

    await page.reload();
    const rows = page.getByRole("table").getByRole("row").filter({ hasText: "Ash" });
    await expect(rows).toHaveCount(1);
    const facilitatorsLeft = await page
      .getByRole("checkbox", { name: /^Select (?!all facilitators$)/ })
      .count();
    await rows.getByRole("link", { name: "Edit" }).click();

    const facts = { facilitatorsLeft, ...(await savedAnswers(page)) };
    expect(facts).toEqual({ facilitatorsLeft: 1, displayName: TARGET, shirt: "L", diet: "vegan" });
    await attachArtifacts(testInfo, {
      name: "merged-facilitator",
      region: page.getByRole("main"),
      facts,
    });
  });
});
