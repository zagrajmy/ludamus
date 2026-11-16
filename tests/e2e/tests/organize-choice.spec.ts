import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { CREW_SPHERE, EMPTY_SPHERE } from "./helpers/urls";

// A sphere's feed offers what the visitor may create there. A manager who may
// create both an event and an encounter (Crew lets its managers create
// encounters) is asked which in a dialog. A manager who may create only an
// event (Empty Sphere keeps encounters off) gets a direct link to its form.

const stateOf = (name: string) => path.join(__dirname, "..", `.auth-state-${name}.json`);

test.describe("with events and encounters on offer", () => {
  test.use({ storageState: stateOf("crew-manager") });

  test("a sphere manager picks an event or an encounter from the organize dialog", async ({
    page,
  }, testInfo) => {
    await page.goto(`${CREW_SPHERE}/`);
    await expect(page.getByRole("link", { name: "Create encounter" })).toHaveCount(0);

    await page.getByRole("link", { name: "Organize" }).click();
    const dialog = page.getByRole("dialog", { name: "What do you want to organize?" });
    await expect(dialog).toBeVisible();
    const event = dialog.getByRole("link", { name: "Event", exact: true });
    const encounter = dialog.getByRole("link", { name: "Encounter", exact: true });
    await expect(event).toHaveAccessibleDescription(/program proposals/);
    await expect(encounter).toHaveAccessibleDescription(/online RPG sessions/);
    await attachArtifacts(testInfo, {
      name: "organize-dialog",
      region: dialog,
      facts: { sphere: CREW_SPHERE, options: ["Event", "Encounter"] },
    });

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();

    await page.getByRole("link", { name: "Organize" }).click();
    await encounter.click();
    await expect(page.getByRole("heading", { level: 1, name: "Create encounter" })).toBeVisible();

    await page.goto(`${CREW_SPHERE}/`);
    await page.getByRole("link", { name: "Organize" }).click();
    await event.click();
    await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
  });
});

test.describe("with only events on offer", () => {
  test.use({ storageState: stateOf("empty") });

  test("a sphere manager goes straight to the event form", async ({ page }, testInfo) => {
    await page.goto(`${EMPTY_SPHERE}/`);
    await expect(page.getByRole("link", { name: "Organize" })).toHaveCount(0);

    const createEvent = page.getByRole("link", { name: "Create event" });
    await attachArtifacts(testInfo, {
      name: "create-event-link",
      region: createEvent,
      facts: { sphere: EMPTY_SPHERE, options: ["Event"] },
    });
    await createEvent.click();
    await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
  });
});
