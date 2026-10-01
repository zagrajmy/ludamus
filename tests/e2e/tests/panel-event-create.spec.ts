import { attachArtifacts } from "./helpers/artifacts";
import { signInAsManager } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: runs add events nobody can delete; a 2001 start keeps /panel/ redirects as is.
const START = "2001-05-04T10:00";
const END = "2001-05-04T18:00";

test.describe("Panel event creation", () => {
  test("organizer creates an event from another event's setup", async ({ page }, testInfo) => {
    const slug = `thornwood-copy-${Date.now()}`;
    await signInAsManager(page);
    await page.goto("/panel/event/thornwood-days/");

    await page.getByRole("link", { name: "New event" }).click();
    await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
    await page.getByLabel("Name").fill("Thornwood Tabletop Days, again");
    await page.getByLabel("Slug").fill(slug);
    await page.getByLabel("Start time").fill(START);
    await page.getByLabel("End time").fill(END);
    await page.getByLabel("Based on").selectOption({ label: "Thornwood Tabletop Days" });
    await page.getByRole("button", { name: "Create event" }).click();

    await page.waitForURL(`**/panel/event/${slug}/`);
    await expect(
      page.getByText(
        "Created Thornwood Tabletop Days, again. It stays hidden until you publish it.",
      ),
    ).toBeVisible();

    await page.goto(`/panel/event/${slug}/venues/`);
    const venues = page.getByRole("main");
    for (const room of ["Thornwood Lodge", "Oak Room", "Birch Room", "Cedar Room"]) {
      await expect(venues.getByText(room, { exact: true }).first()).toBeVisible();
    }
    await attachArtifacts(testInfo, {
      name: "copied-venues",
      region: venues,
      facts: { slug, copiedFrom: "thornwood-days" },
    });
  });
});
