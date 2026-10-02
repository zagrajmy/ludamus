import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { disbandParty, foundParty, type Party } from "./helpers/parties";

// NOTE: Oona Brisk leads, Tamsin Reed is invited (bootstrap_data.py). Oona
// manages two companions who are both called "Pip". Each run founds a party of
// its own and deletes it at the end.
const e2eDir = path.join(__dirname, "..");
test.use({ storageState: path.join(e2eDir, ".auth-state-party-leader.json") });

const INVITEE_EMAIL = "e2e-party-invitee@test.local";
const INVITEE = "Tamsin Reed";
const COMPANION = "Pip";

const PARTIES_URL = "/crowd/profile/parties/";

test.describe("Party refusals", () => {
  let party: Party;

  test.beforeEach(async ({ page }) => {
    party = await foundParty(page, "Harbour Watch");
  });

  test.afterEach(async ({ page }) => {
    await disbandParty(page, party);
  });

  test("a blank invite and an ambiguous companion are refused, and a stale decline says the invite is gone", async ({
    page,
    browser,
  }, testInfo) => {
    await page.getByRole("link", { name: "Invite a member" }).click();
    const inviteDialog = page.getByRole("dialog", { name: "Invite a member" });
    // NOTE: spaces get past the browser's required check; the server has to refuse.
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
    await companionName.fill(COMPANION);
    await companionDialog.getByRole("button", { name: "Add companion" }).click();
    await expect(
      page.getByText("More than one companion has that display name. Rename one first."),
    ).toBeVisible();
    await expect(companionDialog).toBeVisible();
    await expect(companionName).toHaveValue(COMPANION);
    await companionDialog.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText(COMPANION, { exact: true })).toHaveCount(0);

    await test.step("the invitee declines from two tabs; the second is told the invite is gone", async () => {
      const invitee = await browser.newContext({
        storageState: path.join(e2eDir, ".auth-state-party-invitee.json"),
      });
      const firstTab = await invitee.newPage();
      const secondTab = await invitee.newPage();
      const inviteText = `Oona Brisk invited you to their party ${party.name}`;
      for (const tab of [firstTab, secondTab]) {
        await tab.goto(PARTIES_URL);
        await expect(tab.getByText(inviteText)).toBeVisible();
      }
      const invite = (tab: Page) => tab.getByRole("listitem").filter({ hasText: inviteText });
      await invite(firstTab).getByRole("button", { name: "Decline" }).click();
      await expect(firstTab.getByText("Invitation declined.")).toBeVisible();
      await expect(firstTab.getByText(inviteText)).toHaveCount(0);
      await invite(secondTab).getByRole("button", { name: "Decline" }).click();
      await expect(secondTab.getByText("This invitation is no longer valid.")).toBeVisible();
      await expect(secondTab.getByText(inviteText)).toHaveCount(0);
      await invitee.close();
    });

    await page.goto(party.url);
    const members = page.getByRole("main").getByRole("listitem");
    await expect(members.filter({ hasText: INVITEE })).toHaveCount(0);
    const facts = {
      party: party.name,
      members: await Promise.all(
        (await members.all()).map(async (member) =>
          (await member.getByRole("paragraph").first().innerText()).trim(),
        ),
      ),
    };
    expect(facts.members).toEqual(["Oona Brisk"]);
    await attachArtifacts(testInfo, {
      name: "party-refusals",
      region: page.getByRole("main"),
      facts,
    });
  });
});
