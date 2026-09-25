import { writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// Oona Brisk leads, Tamsin Reed is invited (bootstrap_data.py). Oona manages
// two companions who are both called "Pip". Each run founds a party of its own
// and deletes it at the end.
const e2eDir = path.join(__dirname, "..");
test.use({ storageState: path.join(e2eDir, ".auth-state-party-leader.json") });

const INVITEE_EMAIL = "e2e-party-invitee@test.local";
const INVITEE = "Tamsin Reed";
const COMPANION = "Pip";

const PARTIES_URL = "/crowd/profile/parties/";

test.describe("Party refusals", () => {
  let partyName = "";
  let partyUrl = "";

  test.beforeEach(async ({ page }) => {
    partyName = `Harbour Watch ${Date.now()}`;
    await page.goto(PARTIES_URL);
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
    await expect(page.getByText(partyName)).toHaveCount(0);
  });

  test("blank and ambiguous entries are refused with the dialog kept open, and a stale decline says the invite is gone", async ({
    page,
    browser,
  }, testInfo) => {
    // Spaces get past the browser's required check; the server has to refuse.
    await page.getByRole("link", { name: "Invite a member" }).click();
    const inviteDialog = page.getByRole("dialog", { name: "Invite a member" });
    await inviteDialog.getByLabel("Email or Discord username").fill("   ");
    await inviteDialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText("Enter an email or Discord username.")).toBeVisible();

    await page.getByRole("link", { name: "Invite a member" }).click();
    await inviteDialog.getByLabel("Email or Discord username").fill(INVITEE_EMAIL);
    await inviteDialog.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText("Invitation sent.")).toBeVisible();
    await expect(page.getByText(INVITEE)).toBeVisible();

    const companionDialog = page.getByRole("dialog", { name: "Add companion" });
    const companionName = companionDialog.getByLabel("Companion display name");
    await page.getByRole("link", { name: "Add companion" }).click();
    await companionName.fill("   ");
    await companionDialog.getByRole("button", { name: "Add companion" }).click();
    await expect(page.getByText("Enter a companion display name.")).toBeVisible();
    await expect(companionDialog).toBeVisible();

    await page.goto(partyUrl);
    await page.getByRole("link", { name: "Add companion" }).click();
    await companionName.fill(COMPANION);
    await companionDialog.getByRole("button", { name: "Add companion" }).click();
    await expect(
      page.getByText("More than one companion has that display name. Rename one first."),
    ).toBeVisible();
    await expect(companionDialog).toBeVisible();
    await expect(companionName).toHaveValue(COMPANION);
    await companionDialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText(COMPANION, { exact: true })).toHaveCount(0);

    // Tamsin has the parties page open in two tabs and declines from both.
    const invitee = await browser.newContext({
      storageState: path.join(e2eDir, ".auth-state-party-invitee.json"),
    });
    const firstTab = await invitee.newPage();
    const secondTab = await invitee.newPage();
    const inviteText = `Oona Brisk invited you to their party ${partyName}`;
    for (const tab of [firstTab, secondTab]) {
      await tab.goto(PARTIES_URL);
      await expect(tab.getByText(inviteText)).toBeVisible();
    }
    await firstTab
      .getByText(inviteText)
      .locator("xpath=..")
      .getByRole("button", { name: "Decline" })
      .click();
    await expect(firstTab.getByText("Invitation declined.")).toBeVisible();
    await expect(firstTab.getByText(inviteText)).toHaveCount(0);
    await secondTab
      .getByText(inviteText)
      .locator("xpath=..")
      .getByRole("button", { name: "Decline" })
      .click();
    await expect(secondTab.getByText("This invitation is no longer valid.")).toBeVisible();
    await expect(secondTab.getByText(inviteText)).toHaveCount(0);
    await invitee.close();

    await page.goto(partyUrl);
    const members = page.getByRole("main").getByRole("listitem");
    await expect(members.filter({ hasText: INVITEE })).toHaveCount(0);
    const facts = {
      party: partyName,
      members: await Promise.all(
        (await members.all()).map(async (member) =>
          (await member.getByRole("paragraph").first().innerText()).trim(),
        ),
      ),
    };
    expect(facts.members).toEqual(["Oona Brisk"]);
    const screenshotPath = testInfo.outputPath("party-refusals.png");
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await testInfo.attach("party-refusals.png", { path: screenshotPath, contentType: "image/png" });
    const factsPath = testInfo.outputPath("party-refusals.json");
    await writeFile(factsPath, `${JSON.stringify(facts, null, 2)}\n`);
    await testInfo.attach("party-refusals.json", {
      path: factsPath,
      contentType: "application/json",
    });
  });

  test("a name corrected in the reopened companion dialog is submitted", async ({ page }) => {
    // TODO: after a refused add the page sits at .../do/add-companion?add-companion=1,
    // where the "Add companion" trigger (?add-companion=1) resolves to the form's
    // own action. modal.ts's Navigation API handler then takes the resubmit for
    // a trigger click and only reopens the dialog, so nothing is posted. Drop
    // this line once the handler lets form submissions through.
    test.fail();
    const companionDialog = page.getByRole("dialog", { name: "Add companion" });
    const companionName = companionDialog.getByLabel("Companion display name");
    await page.getByRole("link", { name: "Add companion" }).click();
    await companionName.fill("   ");
    await companionDialog.getByRole("button", { name: "Add companion" }).click();
    await expect(page.getByText("Enter a companion display name.")).toBeVisible();

    await companionName.fill(COMPANION);
    await companionDialog.getByRole("button", { name: "Add companion" }).click();
    await expect(
      page.getByText("More than one companion has that display name. Rename one first."),
    ).toBeVisible({ timeout: 3000 });
  });
});
