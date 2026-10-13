import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// A manager sends a Comms invitation link and the invitee joins through it.
// The invitee is e2e-invitee, seeded on no sphere's team so this spec is the
// only thing that ever makes them a member. Expiry, revoking, foreign spheres
// and private spheres are covered by tests/integration/web/multiverse/test_team.py.

test.use({ storageState: path.join(__dirname, "..", ".auth-state-invitee.json") });

test("a manager's invitation link adds the invitee to the team", async ({
  page,
  browser,
}, testInfo) => {
  const managerContext = await browser.newContext({ storageState: undefined });
  const manager = await managerContext.newPage();
  await signInAsManager(manager);

  await manager.goto("/multiverse/panel/team/");
  await manager.getByRole("radio", { name: /^Comms:/ }).check();
  await manager.getByRole("button", { name: "Create invitation link" }).click();
  await expect(
    manager.getByText("Invitation link created. Copy it and send it to the person."),
  ).toBeVisible();
  const link = await manager.getByRole("textbox", { name: "Invitation link" }).first().inputValue();
  expect(link).toContain("/multiverse/join/");
  await managerContext.close();

  await page.goto(new URL(link).pathname);
  await expect(page.getByText("invited you to this sphere's comms team.")).toBeVisible();
  await page.getByRole("button", { name: "Join the team" }).click();

  await expect(page).toHaveURL(/\/multiverse\/panel\/team\/$/);
  await expect(page.getByText("You joined the sphere's team.")).toBeVisible();
  const invitee = page.getByRole("listitem").filter({ hasText: "Ida Invitee" });
  await expect(invitee).toContainText("Comms");

  // The link is spent: opening it again explains instead of granting twice.
  await page.goto(new URL(link).pathname);
  await expect(page.getByText(/This invitation link is no longer valid/)).toBeVisible();

  await page.goto("/multiverse/panel/team/");
  await attachArtifacts(testInfo, {
    name: "sphere-invitation-accepted",
    region: page.getByRole("region", { name: "Members" }),
    facts: { invitee: "Ida Invitee", role: "comms", linkSpentAfterUse: true },
  });
});
