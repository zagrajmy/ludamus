import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { disbandParty, foundParty } from "./helpers/parties";

// NOTE: Oona Brisk leads (bootstrap_data.py), and nobody else signs up on Party
// Table Demo. The run founds a party of its own and deletes it at the end.
const e2eDir = path.join(__dirname, "..");
test.use({ storageState: path.join(e2eDir, ".auth-state-party-leader.json") });

const EVENT_URL = "/event/enroll-states/";
const SESSION = "Party Table Demo";
// NOTE: the browser carries the party choice's #enrollment across the redirect.
const BACK_ON_EVENT = new RegExp(`${EVENT_URL}(#.*)?$`);

const openEnrollPage = async (page: Page) => {
  await page.goto(EVENT_URL);
  await page.getByRole("link", { name: `Open details for ${SESSION}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: SESSION });
  await expect(dialog).toBeVisible();
  const sessionId = (await dialog.getAttribute("id"))!.replace("session-", "");
  await page.goto(`${EVENT_URL}session/${sessionId}/enrollment/`);
  await expect(page.getByRole("heading", { name: SESSION, level: 1 })).toBeVisible();
};

// NOTE: a seat a killed run left would turn the next submit into a no-op.
const leave = async (page: Page) => {
  await openEnrollPage(page);
  const own = page.getByRole("listitem").filter({ hasText: "Already enrolled" });
  if ((await own.count()) === 0) return;
  await own.getByRole("checkbox").uncheck();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page).toHaveURL(BACK_ON_EVENT);
};

test("a new party enrolls together once its leader enrolls through it", async ({
  page,
}, testInfo) => {
  await leave(page);
  const party = await foundParty(page, "Wednesday Table");
  await expect(page.getByRole("heading", { name: "Sessions together" })).toHaveCount(0);

  await openEnrollPage(page);
  const choice = page.getByRole("tablist", { name: "Enrolling as" });
  await choice.getByRole("tab", { name: party.name }).click();
  await expect(choice.getByRole("tab", { name: party.name })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(
    page.getByText("Enrolling turns on enrolling together for this party."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Join this session" }).click();
  await expect(page).toHaveURL(BACK_ON_EVENT);

  await page.goto(party.url);
  const together = page.getByRole("heading", { name: "Sessions together" });
  await expect(together).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading", { name: SESSION })).toBeVisible();

  await attachArtifacts(testInfo, {
    name: "party-enrolls-together",
    region: page.getByRole("main"),
    facts: { party: party.name, session: SESSION, enrollsTogether: true },
  });

  await leave(page);
  await disbandParty(page, party);
});
