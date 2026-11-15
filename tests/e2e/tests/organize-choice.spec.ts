import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { CREW_SPHERE } from "./helpers/urls";

// A sphere manager's create button asks what to organize: an event, built in
// the panel, or an encounter. Crew is a non-root sphere, so its `/` is the
// events feed that carries the button. A member who cannot organize events
// keeps the direct "Create Encounter" button (tests/integration/web/test_index_page.py).

test.use({ storageState: path.join(__dirname, "..", ".auth-state-crew-manager.json") });

test("a sphere manager picks an event or an encounter from the organize dialog", async ({
  page,
}, testInfo) => {
  await page.goto(`${CREW_SPHERE}/`);
  await expect(page.getByRole("link", { name: "Create Encounter" })).toHaveCount(0);

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

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  await page.getByRole("link", { name: "Organize" }).click();
  await encounter.click();
  await expect(page.getByRole("heading", { level: 1, name: "Create Encounter" })).toBeVisible();

  await page.goto(`${CREW_SPHERE}/`);
  await page.getByRole("link", { name: "Organize" }).click();
  await event.click();
  await expect(page.getByRole("heading", { name: "New event" })).toBeVisible();
});
