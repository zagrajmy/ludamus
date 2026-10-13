import fs from "node:fs";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";
import { BASE_URL, CREW_SPHERE } from "./helpers/urls";

// An unlisted event opens for anyone holding its link, before its publication
// time, and is listed nowhere. bootstrap_data.py seeds one, unpublished, in
// the root sphere and one in Crew, a non-root sphere: `/` is the landing page
// or a dashboard on the root and the events feed everywhere else, so the
// "listed nowhere" half has to be checked on both.

const SPHERES = [
  { label: "root sphere", origin: BASE_URL, unlisted: "Root Sneak Peek", slug: "root-sneak-peek" },
  {
    label: "non-root sphere",
    origin: CREW_SPHERE,
    unlisted: "Crew Sneak Peek",
    slug: "crew-sneak-peek",
  },
];

for (const sphere of SPHERES) {
  test.describe(`unlisted event (${sphere.label})`, () => {
    test("opens by link for a signed-out visitor", async ({ page }) => {
      const response = await page.goto(`${sphere.origin}/event/${sphere.slug}/`);

      expect(response?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1, name: sphere.unlisted })).toBeVisible();
    });

    test("is not listed on the sphere's front page", async ({ page }) => {
      await page.goto(`${sphere.origin}/`);

      await expect(page.getByText(sphere.unlisted)).toHaveCount(0);
    });
  });
}

test("a non-root sphere's feed lists its public event and not the unlisted one", async ({
  page,
}) => {
  await page.goto(`${CREW_SPHERE}/`);

  await expect(page.getByText("Crew Open Night")).toBeVisible();
  await expect(page.getByText("Crew Sneak Peek")).toHaveCount(0);
});

test("the non-root sphere's manager sees the unlisted event marked as such", async ({
  browser,
}, testInfo) => {
  const statePath = path.join(__dirname, "..", ".auth-state-crew-manager.json");
  const storageState = JSON.parse(fs.readFileSync(statePath, "utf8"));
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  await page.goto(`${CREW_SPHERE}/`);

  const card = page.getByRole("link").filter({ hasText: "Crew Sneak Peek" });
  await expect(card).toContainText("Link only");
  await expect(page.getByRole("link").filter({ hasText: "Crew Open Night" })).not.toContainText(
    "Link only",
  );
  await attachArtifacts(testInfo, {
    name: "unlisted-event-card",
    region: card,
    facts: { sphere: CREW_SPHERE, event: "Crew Sneak Peek", badge: "Link only" },
  });
  await context.close();
});

test("the root sphere's manager dashboard leaves the unlisted event out", async ({ page }) => {
  await signInAsManager(page);

  await page.goto(`${BASE_URL}/`);

  await expect(page.getByRole("heading", { name: "Your dashboard" })).toBeVisible();
  await expect(page.getByText("Root Sneak Peek")).toHaveCount(0);
});
