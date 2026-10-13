import { type Browser, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";
import { BASE_URL, CREW_SPHERE } from "./helpers/urls";

// A manager sends a Comms invitation link and the invitee joins through it, on
// the root sphere and on a non-root one. The invitee is e2e-invitee, seeded on
// no sphere's team so this spec is the only thing that makes them a member.
// Expiry, revoking, foreign spheres and private spheres are covered by
// tests/integration/web/multiverse/test_team.py.

test.use({ storageState: path.join(__dirname, "..", ".auth-state-invitee.json") });

const SPHERES = [
  {
    label: "root sphere",
    origin: BASE_URL,
    signIn: async (page: Page) => signInAsManager(page),
  },
  {
    label: "non-root sphere",
    origin: CREW_SPHERE,
    // Crew's manager holds a session cookie for that host, written by
    // bootstrap_data.py, so there is nothing to sign in to.
    signIn: async () => {},
    storageState: path.join(__dirname, "..", ".auth-state-crew-manager.json"),
  },
];

const managerPage = async (browser: Browser, sphere: (typeof SPHERES)[number]): Promise<Page> => {
  const storageState =
    "storageState" in sphere ? JSON.parse(fs.readFileSync(sphere.storageState, "utf8")) : undefined;
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();
  await sphere.signIn(page);
  return page;
};

for (const sphere of SPHERES) {
  test(`a manager's invitation link adds the invitee to the team (${sphere.label})`, async ({
    page,
    browser,
  }, testInfo) => {
    const manager = await managerPage(browser, sphere);
    await manager.goto(`${sphere.origin}/multiverse/panel/team/`);
    await manager.getByRole("radio", { name: /^Comms:/ }).check();
    await manager.getByLabel("Who is it for?").fill("Ida");
    await manager.getByRole("button", { name: "Create invitation link" }).click();
    // The open invitation itself, not the toast announcing it: transient
    // flashes clear themselves after five seconds, which a slow load outlasts.
    const link = await manager
      .getByRole("textbox", { name: "Invitation link for Ida" })
      .inputValue();
    // The link names the sphere's own host, so it works when pasted anywhere.
    expect(link.startsWith(`${sphere.origin}/multiverse/join/`)).toBe(true);
    await manager.context().close();

    await page.goto(link);
    await expect(page.getByText("invited you to this sphere's team.")).toBeVisible();
    await expect(
      page.getByText("You'll join as Ida Invitee (e2e-invitee@test.local)."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Join the team" }).click();

    await expect(page).toHaveURL(`${sphere.origin}/multiverse/panel/team/`);
    const invitee = page.getByRole("listitem").filter({ hasText: "Ida Invitee" });
    await expect(invitee).toContainText("Comms");
    await expect(invitee).toContainText("(you)");

    // The link is spent, and its new member is told they are in rather than
    // sent off to ask for another link.
    await page.goto(link);
    await expect(page.getByText("You're already on this sphere's team (Comms).")).toBeVisible();
    await expect(page.getByRole("button", { name: "Join the team" })).toHaveCount(0);

    await page.goto(`${sphere.origin}/multiverse/panel/team/`);
    await attachArtifacts(testInfo, {
      name: `sphere-invitation-accepted-${sphere.label.replace(/ /g, "-")}`,
      region: page.getByRole("region", { name: "Members" }),
      facts: {
        sphere: sphere.origin,
        invitee: "Ida Invitee",
        role: "comms",
        linkSpentAfterUse: true,
      },
    });
  });
}
