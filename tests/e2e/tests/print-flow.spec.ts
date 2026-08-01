import { expect, test } from "./helpers/fixtures";

const printUrl = "/event/kapitularz-2025-anonymized/print/";
const eventName = "Kapitularz 2025 Anonymized";

// The sidebar is not a form: every control rewrites its own query param and
// reloads (src/print-controls.ts). These tests drive the controls the way a
// user would and assert the URL and the rendered preview stay in sync.
test.describe("Print page controls", () => {
  test("track timetable material reveals the track select and scopes the grid", async ({
    page,
  }) => {
    await page.goto(printUrl);

    await page.getByLabel("Printable").selectOption("track-timetable");
    await expect(page).toHaveURL(/material=track-timetable/);

    // No load-state wait: even if this fires before print-controls.ts runs,
    // the module's healing pass applies the missed edit on init. The long
    // timeout absorbs dev-server contention — the track page renders 200 KB
    // of grid and can take >10 s with parallel workers on the shared server.
    const trackSelect = page.getByLabel("Track");
    await expect(trackSelect).toBeVisible();
    await trackSelect.selectOption("rpg");
    await expect(page).toHaveURL(/track=rpg/, { timeout: 30_000 });
    // Untouched params survive a change to another control.
    await expect(page).toHaveURL(/material=track-timetable/);

    const preview = page.getByRole("region", { name: "Print preview" });
    await expect(preview.getByRole("group").first()).toContainText("RPG Table");
  });

  test("scope select narrows the preview to the chosen node", async ({ page }) => {
    await page.goto(`${printUrl}?material=timetable`);

    const scopeSelect = page.getByLabel("Scope");
    const option = scopeSelect.locator("option").nth(1);
    const value = (await option.getAttribute("value"))!;
    const label = (await option.textContent())!.trim();
    await scopeSelect.selectOption(value);

    await expect(page).toHaveURL(new RegExp(`scope=${value}`));
    const preview = page.getByRole("region", { name: "Print preview" });
    await expect(preview.getByRole("group").first()).toBeVisible();
    await expect(preview.getByText(label).first()).toBeVisible();
  });

  test("hours window clips the preview to fewer pages", async ({ page }) => {
    await page.goto(`${printUrl}?material=timetable`);
    const preview = page.getByRole("region", { name: "Print preview" });
    const fullCount = await preview.getByRole("group").count();
    expect(fullCount).toBeGreaterThan(1);

    await page.getByLabel("Hours").fill("4");
    await page.getByLabel("Hours").press("Tab");

    await expect(page).toHaveURL(/hours=4/);
    await expect.poll(async () => preview.getByRole("group").count()).toBeLessThan(fullCount);
    expect(await preview.getByRole("group").count()).toBeGreaterThan(0);
  });

  test("legacy timetable-descriptions URLs map to the checkbox", async ({ page }) => {
    await page.goto(`${printUrl}?material=timetable-descriptions`);

    await expect(page.getByLabel("With descriptions")).toBeChecked();
    await expect(page.getByRole("heading", { name: "Program details" }).first()).toBeVisible();
  });
});

test.describe("Panel print pages", () => {
  test.beforeEach(async ({ page }) => {
    // Log in via Django admin as the manager user (same flow as panel.spec.ts;
    // domcontentloaded because Firefox occasionally never fires `load` here).
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("print materials hub offers timetable and door cards", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/print/");

    await expect(page.getByRole("heading", { name: "Print Materials" })).toBeVisible();
    await expect(page.getByText("Print timetable").first()).toBeVisible();
    await expect(page.getByText("Print door cards").first()).toBeVisible();
  });

  test("panel timetable printout shows session-time rows", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/timetable/print/timetable/");

    await expect(page.getByText(eventName).first()).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Time", exact: true }).first(),
    ).toBeVisible();
    // Session times, not 4-hour availability slots: an 11:00–13:00 session
    // renders as its own row.
    await expect(page.getByRole("cell", { name: /11:00–13:00/ }).first()).toBeVisible();

    // A sheet torn off the stack still names its event, so every page repeats
    // the header rather than only the first one carrying it.
    const sheets = page.locator("section.sheet");
    expect(await sheets.count()).toBeGreaterThan(1);
    for (const sheet of await sheets.all()) {
      await expect(sheet.getByText(eventName).first()).toBeVisible();
    }
  });

  test("door cards render one card per room and day", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/timetable/print/door-cards/");

    // Only rooms with sessions get a card; Miniature Painting always has some,
    // spread over the three seeded days, so it gets one sheet per day.
    const roomHeadings = page.getByRole("heading", { name: "Miniature Painting", exact: true });
    await expect(roomHeadings.first()).toBeVisible();
    expect(await roomHeadings.count()).toBeGreaterThan(1);
    await expect(page.getByText("Capacity: 18").first()).toBeVisible();

    // One h1 for the document, then one room and one day per sheet.
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    const cards = page.locator("section.sheet");
    expect(await cards.count()).toBeGreaterThan(0);
    for (const card of await cards.all()) {
      await expect(card.getByRole("heading", { level: 2 })).toHaveCount(1);
      await expect(card.getByRole("heading", { level: 3 })).toHaveCount(1);
      await expect(card.getByText(eventName).first()).toBeVisible();
    }
  });
});
