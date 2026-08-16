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

  test("door cards print one sheet per room and day", async ({ page }) => {
    await page.goto(`${printUrl}?material=door-cards`);

    // Miniature Painting is the only room in its track and the seed schedules
    // it on all three days, so it gets exactly three sheets — one per day.
    await expect(
      page.getByRole("heading", { name: "Miniature Painting", exact: true }),
    ).toHaveCount(3);
    await expect(page.getByText("Capacity: 18").first()).toBeVisible();

    // One room and one day per sheet, the event named on every sheet — a card
    // torn off the stack still says where and when it belongs.
    const preview = page.getByRole("region", { name: "Print preview" });
    const cards = preview.getByRole("group");
    const labels: string[] = [];
    for (const card of await cards.all()) {
      const room = card.getByRole("heading", { level: 2 });
      const day = card.getByRole("heading", { level: 3 });
      await expect(room).toHaveCount(1);
      await expect(day).toHaveCount(1);
      await expect(card.getByText(eventName).first()).toBeVisible();
      labels.push(`${await room.innerText()}|${await day.innerText()}`);
    }
    // No room+day is printed twice.
    expect(new Set(labels).size).toBe(labels.length);
  });

  test("door cards with descriptions render program details", async ({ page }) => {
    await page.goto(`${printUrl}?material=door-cards`);

    await page.getByLabel("With descriptions").check();

    await expect(page).toHaveURL(/descriptions=1/);
    await expect(page.getByRole("heading", { name: "Program details" }).first()).toBeVisible();
    await expect(page.getByText("Rpg: Archive open tournament 110", { exact: true })).toBeVisible();
  });
});

test.describe("Print page for managers", () => {
  test.beforeEach(async ({ page }) => {
    // Log in via Django admin as the manager user (same flow as panel.spec.ts;
    // domcontentloaded because Firefox occasionally never fires `load` here).
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("the unconfirmed-sessions toggle applies itself to the URL", async ({ page }) => {
    await page.goto(printUrl);

    const box = page.getByLabel("Include unconfirmed sessions");
    await box.check();

    await expect(page).toHaveURL(/unconfirmed=1/);
    await expect(page.getByLabel("Include unconfirmed sessions")).toBeChecked();
  });

  test("panel links lead to the canonical print page", async ({ page }) => {
    await page.goto("/panel/event/kapitularz-2025-anonymized/timetable/");

    // Sidebar "Print Materials" and the schedule toolbar "Print" both point at
    // the public print page — the panel renders no print pages of its own.
    await expect(page.getByRole("link", { name: "Print Materials" })).toHaveAttribute(
      "href",
      printUrl,
    );
    await expect(page.getByRole("link", { name: "Print", exact: true })).toHaveAttribute(
      "href",
      printUrl,
    );
  });
});
