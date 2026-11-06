import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { disbandParty, type Party } from "./helpers/parties";

// NOTE: Oona Brisk leads (bootstrap_data.py). The run founds a party of its own
// and deletes it at the end.
const e2eDir = path.join(__dirname, "..");
test.use({ storageState: path.join(e2eDir, ".auth-state-party-leader.json") });

const PARTIES_URL = "/crowd/profile/parties/";

test("a play party hides enrollment until its leader turns it on", async ({ page }, testInfo) => {
  const name = `Wednesday Table ${Date.now()}`;
  await page.goto(PARTIES_URL);
  await page.getByRole("link", { name: "Create play party", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create play party" });
  await dialog.getByLabel("Party name").fill(name);
  await dialog.getByRole("button", { name: "Create party", exact: true }).click();
  await expect(page).toHaveURL(/\/crowd\/profile\/parties\/\d+\/$/);
  const party: Party = { name, url: page.url() };

  await expect(page.getByRole("heading", { name: "Sessions together" })).toHaveCount(0);

  await page.goto(PARTIES_URL);
  const row = page.locator(".card", { hasText: name });
  await expect(row.getByText("enrolls together")).toHaveCount(0);

  await page.goto(party.url);
  await page.getByRole("button", { name: "Turn on enrolling together" }).click();
  await expect(page.getByText("This party can now enroll together.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sessions together" })).toBeVisible();

  await page.goto(PARTIES_URL);
  await expect(row.getByText("enrolls together")).toBeVisible();

  await attachArtifacts(testInfo, {
    name: "party-enrolls-together",
    region: row,
    facts: { party: name, enrollsTogether: true },
  });

  await disbandParty(page, party);
});
