import { writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// NOTE: Corwin Vale manages one companion, Bramble Vale (bootstrap_data.py). Each run
// founds a party of its own and deletes it at the end.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-party-host.json") });

const LEADER = "Corwin Vale";
const COMPANION = "Bramble Vale";

test.describe("Party companion dialog", () => {
  let partyName = "";
  let partyUrl = "";

  test.beforeEach(async ({ page }) => {
    partyName = `Lantern Crew ${Date.now()}`;
    await page.goto("/crowd/profile/parties/");
    await page.getByRole("link", { name: "Create party", exact: true }).click();
    const createDialog = page.getByRole("dialog", { name: "Create party" });
    await createDialog.getByLabel("Party name").fill(partyName);
    await createDialog.getByRole("button", { name: "Create party", exact: true }).click();
    await expect(page).toHaveURL(/\/crowd\/profile\/parties\/\d+\/$/);
    partyUrl = page.url();
  });

  test.afterEach(async ({ page }) => {
    await page.goto(partyUrl);
    await page.getByRole("button", { name: "Delete party" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete party" }).click();
    await expect(page.getByText("Party deleted.")).toBeVisible();
  });

  test("a name corrected in the reopened dialog is submitted and joins the roster", async ({
    page,
  }, testInfo) => {
    const dialog = page.getByRole("dialog", { name: "Add companion" });
    const name = dialog.getByLabel("Companion display name");
    const members = page.getByRole("main").getByRole("listitem");

    await page.getByRole("link", { name: "Add companion" }).click();
    await expect(dialog).toBeVisible();
    // NOTE: spaces get past the browser's required check; the server has to refuse.
    await name.fill("   ");
    await dialog.getByRole("button", { name: "Add companion" }).click();
    await expect(page.getByText("Enter a companion display name.")).toBeVisible();
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/\/do\/add-companion\?add-companion=1$/);

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("link", { name: "Add companion" }).click();
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/\/do\/add-companion\?add-companion=1$/);

    // NOTE: the dialog's form posts to the very URL the page now sits at, which is
    // also where the "Add companion" link points.
    await name.fill(COMPANION);
    await dialog.getByRole("button", { name: "Add companion" }).click();
    await expect(page.getByText("Companion added to the party.")).toBeVisible();
    await expect(page).toHaveURL(partyUrl);
    await expect(dialog).toBeHidden();

    await page.reload();
    await expect(members.filter({ hasText: COMPANION })).toHaveCount(1);

    const facts = {
      party: partyName,
      members: await Promise.all(
        (await members.all()).map(async (member) =>
          (await member.getByRole("paragraph").first().innerText()).trim(),
        ),
      ),
    };
    expect(facts.members).toEqual([LEADER, COMPANION]);
    const screenshotPath = testInfo.outputPath("party-companion.png");
    await page.getByRole("main").screenshot({ path: screenshotPath });
    await testInfo.attach("party-companion.png", {
      path: screenshotPath,
      contentType: "image/png",
    });
    const factsPath = testInfo.outputPath("party-companion.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("party-companion.json", {
      path: factsPath,
      contentType: "application/json",
    });
  });
});
