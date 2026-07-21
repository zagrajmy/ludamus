import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/** Accept the in-page confirm modal that guards destructive forms. */
const acceptConfirmModal = (page: Page) =>
  page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();

/** Open a space-tree node's "More actions" menu; returns the menu locator. */
const openSpaceMenu = async (page: Page, name: string): Promise<Locator> => {
  const toggle = page.getByRole("button", {
    name: `More actions for ${name}`,
    exact: true,
  });
  await toggle.click();
  return page.locator("[data-menu]", { has: toggle }).locator("[data-menu-panel]");
};

/** Build an HH:MM string by adding minutes to a base hour:minute. */
function timeHHMM(hour: number, minute: number, addMinutes: number = 0): string {
  const d = new Date(2000, 0, 1, hour, minute + addMinutes);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Compute both YYYY-MM-DD and HH:MM after adding minutes to a base datetime.
 * Handles midnight rollover by advancing the date.
 */
function dateTimeAfter(
  baseDateStr: string,
  hour: number,
  minute: number,
  addMinutes: number = 0,
): { date: string; time: string } {
  const [y, m, day] = baseDateStr.split("-").map(Number);
  const d = new Date(y, m - 1, day, hour, minute + addMinutes);
  const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const ts = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return { date: ds, time: ts };
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function sessionTypeRequirementSelect(page: Page, name: string) {
  return page.getByRole("combobox", { name, exact: true }).last();
}

function firstCategoryRequirementSelect(page: Page) {
  return page.locator('select[name^="category_"]').first();
}

async function expectRequiredOption(
  select: Locator,
  expected: { hidden: boolean; disabled: boolean },
) {
  await expect
    .poll(() =>
      select.locator('option[value="required"]').evaluate((opt: HTMLOptionElement) => ({
        hidden: opt.hidden,
        disabled: opt.disabled,
      })),
    )
    .toEqual(expected);
}

function proposalCategoryOption(page: Page, name: string) {
  return page.getByText(name, { exact: true }).last();
}

test("panel redirects to home with message when sphere has no events", async ({ browser }) => {
  const emptyBase = "http://another.localhost:8000";

  // Use pre-built session cookie for the empty-sphere manager
  const statePath = path.join(__dirname, "..", ".auth-state-empty.json");
  const storageState = JSON.parse(fs.readFileSync(statePath, "utf8"));
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  // Visit panel — should redirect to index (then to /events/)
  await page.goto(`${emptyBase}/panel/`);
  await expect(page).toHaveURL(`${emptyBase}/events/`);
  await expect(page.getByText("No events available")).toBeVisible();

  await context.close();
});

test.describe.configure({ mode: "serial" });

test.describe("Backoffice Panel", () => {
  test.beforeEach(async ({ page }) => {
    // Log in via Django admin as the manager user.
    // Use domcontentloaded — the login form is interactable at DCL and
    // Firefox occasionally never fires `load` for this page, hanging the
    // default goto until the test timeout (CI run 25398374365).
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("opens panel dashboard with sidebar and stats", async ({ page }) => {
    await page.goto("/panel/");

    // /panel/ redirects to the first event's dashboard
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);

    // Sidebar navigation
    await expect(page.getByRole("link", { name: /Dashboard/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Call for Proposals/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Proposals", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /Venues/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Event Settings/ })).toBeVisible();

    // Page header
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Stats cards (scoped to main so "Facilitators" doesn't also match the
    // sidebar nav link of the same name).
    const stats = page.getByRole("main");
    await expect(stats.getByText("All Sessions")).toBeVisible();
    await expect(stats.getByText("Facilitators")).toBeVisible();
    await expect(stats.getByText("Rooms")).toBeVisible();

    // Event selector in sidebar
    await expect(page.locator("#eventSelector")).toBeVisible();

    await page.screenshot({
      path: "test-results/panel-dashboard.png",
      fullPage: true,
    });
  });

  // --- Step 1: Event Settings ---

  test("navigates to event settings and displays form", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/settings/");

    await expect(page.getByRole("heading", { name: "Event Settings" })).toBeVisible();

    // Sidebar link active
    await expect(page.getByRole("link", { name: /Event Settings/ })).toBeVisible();

    // Name input pre-filled
    await expect(page.locator("#id_name")).toHaveValue("Frostfire Game Convention");

    // Save button visible
    await expect(page.getByRole("button", { name: "Save Settings" })).toBeVisible();
  });

  test("updates event name via settings form", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/settings/");

    const nameInput = page.locator("#id_name");
    await nameInput.fill("Frostfire Game Convention Renamed");
    await page.getByRole("button", { name: "Save Settings" }).click();

    // Verify success message
    await expect(page.getByText("Event settings saved successfully.")).toBeVisible();

    // Verify input shows new name
    await expect(nameInput).toHaveValue("Frostfire Game Convention Renamed");

    // Restore original name
    await nameInput.fill("Frostfire Game Convention");
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Event settings saved successfully.")).toBeVisible();
  });

  // --- Step 2: Venues List, Create, Detail, Edit ---

  test("lists the space tree for the event", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");

    await expect(page.getByText("Aurora Convention Hall", { exact: true })).toBeVisible();
    await expect(page.getByText("Hearth Lounge", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "New top-level space" })).toBeVisible();
  });

  test("creates a top-level space", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");
    await page.getByRole("link", { name: "New top-level space" }).click();

    await page.locator("#id_name").fill("Community Library");
    await page.locator("#id_description").fill("456 Book Lane");
    await page.getByRole("button", { name: "Create space" }).click();

    await expect(page.getByText("Space created successfully.")).toBeVisible();
    await expect(page.getByText("Community Library", { exact: true })).toBeVisible();
  });

  test("creates a nested space inside a parent", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");
    await page.getByRole("link", { name: "Add a space inside Aurora Convention Hall" }).click();

    await page.locator("#id_name").fill("Workshop Room");
    await page.locator("#id_capacity").fill("15");
    await page.getByRole("button", { name: "Create space" }).click();

    await expect(page.getByText("Space created successfully.")).toBeVisible();
    await expect(page.getByText("Workshop Room", { exact: true })).toBeVisible();
  });

  test("edits a space", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");
    await page.getByRole("link", { name: "Edit Frost Gallery" }).click();

    await expect(page.locator("#id_name")).toHaveValue("Frost Gallery");

    await page.locator("#id_capacity").fill("40");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Space updated successfully.")).toBeVisible();

    // Restore original capacity
    await page.getByRole("link", { name: "Edit Frost Gallery" }).click();
    await page.locator("#id_capacity").fill("30");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Space updated successfully.")).toBeVisible();
  });

  // --- Tree node actions: Duplicate, Copy, Delete ---

  test("duplicates a space", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");

    const menu = await openSpaceMenu(page, "Aurora Convention Hall");
    await menu.getByRole("button", { name: "Duplicate" }).click();

    await expect(page.getByText("Space duplicated successfully.")).toBeVisible();
  });

  test("copies a space to another event", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/venues/");

    const menu = await openSpaceMenu(page, "Aurora Convention Hall");
    await menu.getByRole("link", { name: "Copy to event" }).click();

    await page.locator("#id_target_event").selectOption({ label: "Retro Mini Jam" });
    await page.getByRole("button", { name: "Copy" }).click();

    await expect(page.getByText("Space copied to Retro Mini Jam successfully.")).toBeVisible();
  });

  test("deletes a space", async ({ page }) => {
    // Create a throwaway top-level space first.
    await page.goto("/panel/event/frostfire-con/venues/");
    await page.getByRole("link", { name: "New top-level space" }).click();
    await page.locator("#id_name").fill("Temp Space To Delete");
    await page.getByRole("button", { name: "Create space" }).click();
    await expect(page.getByText("Space created successfully.")).toBeVisible();

    const menu = await openSpaceMenu(page, "Temp Space To Delete");
    await menu.getByRole("button", { name: "Delete" }).click();
    await acceptConfirmModal(page);

    await expect(page.getByText("Space deleted successfully.")).toBeVisible();
  });

  // --- Step 6: CFP Session Types ---

  test("shows CFP page and creates a session type", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/cfp/");

    await expect(page.getByRole("heading", { name: "Call for Proposals" })).toBeVisible();
    await expect(page.getByRole("link", { name: "New Category" })).toBeVisible();

    // Create a session type
    await page.getByRole("link", { name: "New Category" }).click();
    await page.locator("#id_name").fill("Board Games");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("Category created successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: "Board Games" }).first()).toBeVisible();
  });

  test("creates session type and navigates to configure", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/cfp/");
    await page.getByRole("link", { name: "New Category" }).click();

    await page.locator("#id_name").fill("RPG Sessions");
    await page.getByRole("button", { name: "Add and configure" }).click();

    await expect(page.getByText("Category created successfully.")).toBeVisible();
    await expect(page).toHaveURL(/\/cfp\/rpg-sessions/);
    await expect(
      page.getByRole("heading", {
        name: "Configure Category",
      }),
    ).toBeVisible();
  });

  test("edits a session type", async ({ page }) => {
    // First create one to edit
    await page.goto("/panel/event/frostfire-con/cfp/");
    await page.getByRole("link", { name: "New Category" }).click();
    await page.locator("#id_name").fill("Workshops");
    await page.getByRole("button", { name: "Add and configure" }).click();
    await expect(page.getByText("Category created successfully.")).toBeVisible();

    // Now edit it
    await page.locator("#id_name").fill("Advanced Workshops");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Category updated successfully.")).toBeVisible();
  });

  test("deletes a session type", async ({ page }) => {
    // Create one to delete
    await page.goto("/panel/event/frostfire-con/cfp/");
    await page.getByRole("link", { name: "New Category" }).click();
    await page.locator("#id_name").fill("Temp Type To Delete");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Category created successfully.")).toBeVisible();

    const row = page.locator("tr", {
      hasText: "Temp Type To Delete",
    });
    await row.getByRole("link", { name: "Configure" }).click();

    // CFP list doesn't have dropdown — delete is on the list via
    // a form button. Go back to list and delete.
    await page.goto("/panel/event/frostfire-con/cfp/");

    const listRow = page.locator("tr", {
      hasText: "Temp Type To Delete",
    });
    await listRow.getByRole("button", { name: /Delete/i }).click();
    await acceptConfirmModal(page);

    await expect(page.getByText("Category deleted successfully.")).toBeVisible();
  });

  // --- Step 7: Fields — Personal Data & Session ---

  test("creates and manages a personal data field", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/cfp/personal-data/");

    await expect(
      page.getByRole("heading", {
        name: "CFP Fields",
      }),
    ).toBeVisible();

    // Create
    await page.getByRole("link", { name: "New Field" }).first().click();
    await page.locator("#id_name").fill("Email");
    await page.locator("#id_question").fill("What is your email?");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("Personal data field created successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: "Email" })).toBeVisible();

    // Edit
    await page.locator("tr", { hasText: "Email" }).getByRole("link", { name: "Edit" }).click();
    await page.locator("#id_question").fill("What is your contact email?");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Personal data field updated successfully.")).toBeVisible();

    // Delete
    await page
      .locator("tr", { hasText: "Email" })
      .getByRole("button", { name: /Delete/i })
      .click();
    await acceptConfirmModal(page);

    await expect(page.getByText("Personal data field deleted successfully.")).toBeVisible();
  });

  test("creates and manages a session field", async ({ page }, testInfo) => {
    // Suffix with retry index so retries after a half-completed attempt do
    // not collide with leftover rows and trip strict-mode locator matches.
    const retrySuffix = testInfo.retry === 0 ? "" : `-r${testInfo.retry}`;
    const fieldName = `Game System ${testInfo.project.name}${retrySuffix}`;
    await page.goto("/panel/event/frostfire-con/cfp/session-fields/");

    await expect(page.getByRole("heading", { name: "CFP Fields" })).toBeVisible();

    // Create
    await page.getByRole("link", { name: "New Field" }).first().click();
    await page.locator("#id_name").fill(fieldName);
    await page.locator("#id_question").fill("What game system?");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("Session field created successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: new RegExp(fieldName) })).toBeVisible();

    // Edit
    await page
      .getByRole("row", { name: new RegExp(fieldName) })
      .getByRole("link", { name: "Edit" })
      .click();
    await page.locator("#id_question").fill("Which game system will you use?");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Session field updated successfully.")).toBeVisible();

    // Delete
    await page
      .getByRole("row", { name: new RegExp(fieldName) })
      .getByRole("button", { name: /Delete/i })
      .click();
    await acceptConfirmModal(page);

    await expect(page.getByText("Session field deleted successfully.")).toBeVisible();
  });

  test('field create forms hide "Required" for checkbox fields', async ({ page }) => {
    for (const path of [
      "/panel/event/frostfire-con/cfp/personal-data/create/",
      "/panel/event/frostfire-con/cfp/session-fields/create/",
    ]) {
      await page.goto(path);

      const requirementSelect = firstCategoryRequirementSelect(page);
      await page.locator("#id_field_type").selectOption("text");
      await requirementSelect.selectOption("required");
      await expectRequiredOption(requirementSelect, {
        hidden: false,
        disabled: false,
      });
      await expect(requirementSelect).toHaveValue("required");

      await page.locator("#id_field_type").selectOption("checkbox");
      await expectRequiredOption(requirementSelect, {
        hidden: true,
        disabled: true,
      });
      await expect(requirementSelect).toHaveValue("optional");
    }
  });

  test("cfp picker shows checkbox fields as optional only", async ({ page }, testInfo) => {
    const retrySuffix = testInfo.retry === 0 ? "" : `-r${testInfo.retry}`;
    const nameSuffix = `${testInfo.project.name}${retrySuffix}`;
    const hostFieldName = `Host Consent ${nameSuffix}`;
    const sessionFieldName = `Session Consent ${nameSuffix}`;

    await page.goto("/panel/event/frostfire-con/cfp/personal-data/create/");
    await page.locator("#id_name").fill(hostFieldName);
    await page.locator("#id_question").fill("May we contact this host?");
    await page.locator("#id_field_type").selectOption("checkbox");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Personal data field created successfully.")).toBeVisible();

    await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
    await page.locator("#id_name").fill(sessionFieldName);
    await page.locator("#id_question").fill("Does this session need consent?");
    await page.locator("#id_field_type").selectOption("checkbox");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Session field created successfully.")).toBeVisible();

    await page.goto("/panel/event/frostfire-con/cfp/rpg-proposals/");

    const assertOptionalOnly = async (group: string, fieldName: string) => {
      await page
        .locator(`${group} .avail-list .field-item`, { hasText: fieldName })
        .locator(".add-field")
        .click();

      const chosen = page.locator(`${group} .chosen-list .field-item`, {
        hasText: fieldName,
      });
      await expect(chosen.locator(".field-select")).toHaveValue("optional");
      await expect(chosen.locator(".toggle-req")).toHaveCount(0);
      await expect(chosen.locator(".optional-label")).toHaveText("Optional");
    };

    await assertOptionalOnly("#host-fields-list", hostFieldName);
    await assertOptionalOnly("#session-fields-list", sessionFieldName);

    await page.goto("/panel/event/frostfire-con/cfp/personal-data/");
    await page
      .getByRole("row", { name: new RegExp(hostFieldName) })
      .getByRole("button", { name: /Delete/i })
      .click();
    await acceptConfirmModal(page);
    await expect(page.getByText("Personal data field deleted successfully.")).toBeVisible();

    await page.goto("/panel/event/frostfire-con/cfp/session-fields/");
    await page
      .getByRole("row", { name: new RegExp(sessionFieldName) })
      .getByRole("button", { name: /Delete/i })
      .click();
    await acceptConfirmModal(page);
    await expect(page.getByText("Session field deleted successfully.")).toBeVisible();
  });

  // --- Step 8: Time Slots ---

  test("shows time slots page", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/cfp/time-slots/");

    await expect(page.getByRole("heading", { name: "Time Slots" })).toBeVisible();
  });

  test("creates, edits, and deletes a time slot", async ({ page }) => {
    // Navigate to time slots page and extract event start info
    await page.goto("/panel/event/frostfire-con/cfp/time-slots/");

    const addLink = page
      .getByRole("link", {
        name: "Add",
        exact: true,
      })
      .first();

    // Extract event start hour from "Event starts at HH:MM" text
    const startsText = await page.getByText(/Event starts at/).textContent();
    const hourMatch = startsText?.match(/starts at (\d{2}):(\d{2})/);
    const baseHour = parseInt(hourMatch?.[1] ?? "9", 10);
    const rawMin = parseInt(hourMatch?.[2] ?? "0", 10);
    // Add 1 minute to avoid seconds-precision issue
    const safeMin = rawMin + 1;

    const bodyText = await page.locator("body").textContent();
    const ranges = [...(bodyText ?? "").matchAll(/(\d{2}):(\d{2})\s+–\s+(\d{2}):(\d{2})/g)].map(
      (match) => ({
        start: Number(match[1]) * 60 + Number(match[2]),
        end: Number(match[3]) * 60 + Number(match[4]),
      }),
    );
    const eventStart = baseHour * 60 + safeMin;
    const eventEnd = eventStart + 239;
    const duration = 5;
    const extendedDuration = 10;
    let startMinute = eventEnd - extendedDuration;
    while (
      startMinute > eventStart &&
      ranges.some(
        (range) => startMinute < range.end && startMinute + extendedDuration > range.start,
      )
    ) {
      startMinute -= 1;
    }
    const startTime = timeHHMM(0, startMinute);
    const endTime = timeHHMM(0, startMinute + duration);
    const updatedEndTime = timeHHMM(0, startMinute + extendedDuration);

    // Click the per-day "Add" link (pre-fills the date)
    await addLink.click();

    // Fill project-specific times so cross-browser runs do not collide.
    await page.locator("#id_start_time").fill(startTime);
    await page.locator("#id_end_time").fill(endTime);
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("Time slot created successfully.")).toBeVisible();
    const createdSlot = page.getByText(`${startTime} – ${endTime}`);
    await expect(createdSlot).toBeVisible();

    // Edit
    await page
      .getByRole("link", { name: "Edit" })
      .filter({ hasNot: page.locator('[href$="/1/edit/"]') })
      .last()
      .click();

    // Extend by 30 min
    await page.locator("#id_end_time").fill(updatedEndTime);
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Time slot updated successfully.")).toBeVisible();
    await expect(page.getByText(`${startTime} – ${updatedEndTime}`)).toBeVisible();

    // Delete
    await page
      .getByRole("button", { name: /Delete/i })
      .last()
      .click();
    await acceptConfirmModal(page);

    await expect(page.getByText("Time slot deleted successfully.")).toBeVisible();
  });

  // --- Step 9: Proposals & Access Control ---

  test("shows proposals page", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/proposals/");

    await expect(page.getByRole("heading", { name: "Proposals" })).toBeVisible();
  });

  test("non-manager user is denied panel access", async ({ browser }) => {
    // Use pre-built session cookie for regular e2e-tester
    const statePath = path.join(__dirname, "..", ".auth-state.json");
    const storageState = JSON.parse(fs.readFileSync(statePath, "utf8"));
    const context = await browser.newContext({ storageState });
    const page = await context.newPage();

    await page.goto("/panel/");

    // Should redirect away from panel
    await expect(page).not.toHaveURL(/\/panel\//);

    await context.close();
  });

  // --- Step 10: Full CFP → Proposal → Panel Verification ---

  test.describe.serial("CFP to proposal to panel flow", () => {
    let proposalCategoryName = "";
    let proposalCategoryPath = "";
    let proposalTitle = "";
    let cityName = "";
    let experienceName = "";
    let newsletterName = "";
    let gameSystemName = "";
    let genreName = "";
    let languagesName = "";
    let beginnerName = "";

    test("creates session type for proposal flow", async ({ page }, testInfo) => {
      const suffix =
        testInfo.retry > 0 ? `${testInfo.project.name}-r${testInfo.retry}` : testInfo.project.name;
      proposalCategoryName = `Tabletop RPG ${suffix}`;
      proposalTitle = `Dragon's Lair ${suffix}: A Beginner Adventure`;
      cityName = `City ${suffix}`;
      experienceName = `Experience Level ${suffix}`;
      newsletterName = `Newsletter ${suffix}`;
      gameSystemName = `Game System ${suffix}`;
      genreName = `Genre ${suffix}`;
      languagesName = `Languages ${suffix}`;
      beginnerName = `Beginner Friendly ${suffix}`;
      await page.goto("/panel/event/frostfire-con/cfp/create/");
      await page.locator("#id_name").fill(proposalCategoryName);
      await page.getByRole("button", { name: "Add and configure" }).click();

      await expect(page.getByText("Category created successfully.")).toBeVisible();
      await expect(
        page.getByRole("heading", {
          name: "Configure Category",
        }),
      ).toBeVisible();
      proposalCategoryPath = new URL(page.url()).pathname;
    });

    test("creates time slots for proposal flow", async ({ page }) => {
      // Get the event date from the time slots page
      await page.goto("/panel/event/frostfire-con/cfp/time-slots/");
      const addLink = page
        .getByRole("link", {
          name: "Add",
          exact: true,
        })
        .first();
      const addHref = await addLink.getAttribute("href");
      // Extract date from ?date= param
      const dateMatch = addHref?.match(/date=(\d{4}-\d{2}-\d{2})/);
      const dateStr = dateMatch?.[1] ?? "";

      // Compute event start hour from "Event starts at HH:MM" text
      const startsText = await page.getByText(/Event starts at/).textContent();
      const hourMatch = startsText?.match(/starts at (\d{2}):(\d{2})/);
      const baseHour = parseInt(hourMatch?.[1] ?? "9", 10);
      // Add 1 minute to avoid seconds-precision issue
      // (event start has seconds, form only takes HH:MM)
      const rawMin = parseInt(hourMatch?.[2] ?? "0", 10);
      const safeMin = rawMin + 1;

      // Create 3 time slots (30min each), starting 2h after event start
      // to avoid overlap with the bootstrapped 10:00–12:00 slot
      for (let i = 0; i < 3; i++) {
        const start = dateTimeAfter(dateStr, baseHour, safeMin, 120 + i * 30);
        const end = dateTimeAfter(dateStr, baseHour, safeMin, 120 + (i + 1) * 30);
        await page.goto("/panel/event/frostfire-con/cfp/time-slots/");
        if (await page.getByText(`${start.time} – ${end.time}`).count()) continue;

        await page.goto("/panel/event/frostfire-con/cfp/time-slots/create/");
        await page.locator("#id_date").fill(start.date);
        await page.locator("#id_end_date").fill(end.date);
        await page.locator("#id_start_time").fill(start.time);
        await page.locator("#id_end_time").fill(end.time);
        await page.getByRole("button", { name: "Create" }).click();

        await expect(page.getByText("Time slot created successfully.")).toBeVisible();
      }
    });

    test("creates personal data fields for proposal flow", async ({ page }) => {
      // Field 1: City (text, required)
      await page.goto("/panel/event/frostfire-con/cfp/personal-data/create/");
      await page.locator("#id_name").fill(cityName);
      await page.locator("#id_question").fill("What city are you from?");
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("required");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Personal data field created successfully.")).toBeVisible();

      // Field 2: Experience Level (select, required)
      await page.goto("/panel/event/frostfire-con/cfp/personal-data/create/");
      await page.locator("#id_name").fill(experienceName);
      await page.locator("#id_question").fill("What is your experience level?");
      await page.locator("#id_field_type").selectOption("select");
      await expect(page.locator("#options-container")).toBeVisible();
      await page.locator("#id_options").fill("Beginner\nIntermediate\nAdvanced");
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("required");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Personal data field created successfully.")).toBeVisible();

      // Field 3: Newsletter (checkbox, optional)
      await page.goto("/panel/event/frostfire-con/cfp/personal-data/create/");
      await page.locator("#id_name").fill(newsletterName);
      await page.locator("#id_question").fill("Subscribe to newsletter?");
      await page.locator("#id_field_type").selectOption("checkbox");
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("optional");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Personal data field created successfully.")).toBeVisible();
    });

    test("creates session fields for proposal flow", async ({ page }) => {
      // Field 1: Game System (text, required)
      await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
      await page.locator("#id_name").fill(gameSystemName);
      await page.locator("#id_question").fill("What game system will you use?");
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("required");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Session field created successfully.")).toBeVisible();

      // Field 2: Genre (select, required)
      await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
      await page.locator("#id_name").fill(genreName);
      await page.locator("#id_question").fill("What genre is your session?");
      await page.locator("#id_field_type").selectOption("select");
      await expect(page.locator("#options-container")).toBeVisible();
      await page.locator("#id_options").fill("Fantasy\nSci-Fi\nHorror");
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("required");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Session field created successfully.")).toBeVisible();

      // Field 3: Languages (select multiple, optional)
      await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
      await page.locator("#id_name").fill(languagesName);
      await page.locator("#id_question").fill("Which languages can you run in?");
      await page.locator("#id_field_type").selectOption("select");
      await expect(page.locator("#options-container")).toBeVisible();
      await page.locator("#id_options").fill("English\nPolish\nGerman");
      await page.locator("#id_is_multiple").check();
      await sessionTypeRequirementSelect(page, proposalCategoryName).selectOption("optional");
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Session field created successfully.")).toBeVisible();

      /* NOTE: the panel UI hides "Required" for checkbox fields because
           the proposer-side form builder (chronology/forms.py — BooleanField
           for checkbox) ignores `is_required` anyway. The regression test
           below needs a checkbox stored as required to exercise that
           defensive coercion, so we re-inject the option to craft a
           tampered POST that the server-side parser still accepts. */
      await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
      await page.locator("#id_name").fill(beginnerName);
      await page.locator("#id_question").fill("Is this session beginner-friendly?");
      await page.locator("#id_field_type").selectOption("checkbox");
      await sessionTypeRequirementSelect(page, proposalCategoryName).evaluate(
        (sel: HTMLSelectElement) => {
          const opt = document.createElement("option");
          opt.value = "required";
          opt.textContent = "Required";
          sel.appendChild(opt);
          sel.value = "required";
        },
      );
      await page.getByRole("button", { name: "Create" }).click();
      await expect(page.getByText("Session field created successfully.")).toBeVisible();
    });

    test("configures session type with all fields and time slots", async ({ page }) => {
      await page.goto(proposalCategoryPath);

      // Set submission window (past to future)
      const now = new Date();
      const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      const nextWeek = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
      const toLocalISO = (d: Date) =>
        d.getFullYear() +
        "-" +
        String(d.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(d.getDate()).padStart(2, "0") +
        "T" +
        String(d.getHours()).padStart(2, "0") +
        ":" +
        String(d.getMinutes()).padStart(2, "0");
      await page.locator("#id_start_time").fill(toLocalISO(yesterday));
      await page.locator("#id_end_time").fill(toLocalISO(nextWeek));

      const ensureChosen = async (group: string, fieldName: string) => {
        const chosen = page.locator(`${group} .chosen-list .field-item`, {
          hasText: fieldName,
        });
        if ((await chosen.count()) === 0) {
          await page
            .locator(`${group} .avail-list .field-item`, {
              hasText: fieldName,
            })
            .locator(".add-field")
            .click();
        }
        await expect(chosen).toBeVisible();
      };

      for (const fieldName of [cityName, experienceName, newsletterName]) {
        await ensureChosen("#host-fields-list", fieldName);
      }

      for (const fieldName of [gameSystemName, genreName, languagesName, beginnerName]) {
        await ensureChosen("#session-fields-list", fieldName);
      }

      // Add all time slots
      const slotAvail = page.locator("#time-slots-list .avail-list .field-item");
      while ((await slotAvail.count()) > 0) {
        await slotAvail.first().locator(".add-field").click();
      }

      // Add a duration: 2h 0min
      await page.locator("#duration-hours").fill("2");
      await page.locator("#duration-minutes").fill("0");
      await page.locator("#add-duration-btn").click();
      await expect(page.locator(".duration-item", { hasText: "2h" })).toBeVisible();

      await page
        .locator("#session-fields-list .field-item", {
          hasText: beginnerName,
        })
        .locator(".field-select")
        .evaluate((sel: HTMLSelectElement) => {
          if (!sel.querySelector('option[value="required"]')) {
            const opt = document.createElement("option");
            opt.value = "required";
            opt.textContent = "Required";
            sel.appendChild(opt);
          }
          sel.value = "required";
        });

      // Save
      await page.getByRole("button", { name: "Save" }).click();

      await expect(page.getByText("Category updated successfully.")).toBeVisible();
    });

    test("submits a proposal through the public wizard", async ({ browser }) => {
      // Use a separate browser context with the e2e-tester user
      const statePath = path.join(__dirname, "..", ".auth-state.json");
      const storageState = JSON.parse(fs.readFileSync(statePath, "utf8"));
      const context = await browser.newContext({
        storageState,
      });
      const page = await context.newPage();

      // Step 1: Category
      await page.goto("/event/frostfire-con/session/propose/");
      await proposalCategoryOption(page, proposalCategoryName).click();
      await page.getByRole("button", { name: /Continue/ }).click();

      // Step 2: Personal Data
      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Your Information",
        }),
      ).toBeVisible();

      await page.locator("#id_contact_email").fill("host@example.com");
      await page.locator(`input[name="personal_${slugify(cityName)}"]`).fill("Krakow");
      await page
        .locator(`select[name="personal_${slugify(experienceName)}"]`)
        .selectOption("Intermediate");
      await page.getByLabel("Subscribe to newsletter?").check();
      await page.getByRole("button", { name: /Continue/ }).click();

      // Step 3: Time Slots
      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Preferred Time Slots",
        }),
      ).toBeVisible();

      // Check 1st and 3rd slot
      const slotLabels = page.locator('label:has(input[name="time_slot_ids"])');
      await slotLabels.nth(0).click();
      await slotLabels.nth(2).click();
      await page.getByRole("button", { name: /Continue/ }).click();

      // Step 4: Session Details
      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Session Details",
        }),
      ).toBeVisible();

      await page.locator("#id_title").fill(proposalTitle);
      await page.locator("#id_description").fill("An introductory RPG session for new players.");
      await page.locator("#id_participants_limit").fill("6");
      await page.locator("#id_display_name").fill("Game Master Alex");
      await page.locator("#id_duration").selectOption("PT2H");
      await page.locator(`input[name="session_${slugify(gameSystemName)}"]`).fill("D&D 5e");
      await page.locator(`select[name="session_${slugify(genreName)}"]`).selectOption("Fantasy");
      await page
        .locator("label", { hasText: "English" })
        .locator(`input[name="session_${slugify(languagesName)}"]`)
        .check();
      await page
        .locator("label", { hasText: "Polish" })
        .locator(`input[name="session_${slugify(languagesName)}"]`)
        .check();
      await page.locator(`input[name="session_${slugify(beginnerName)}"]`).check();
      await page.getByRole("button", { name: /Continue/ }).click();

      // Step 5: Review & Submit
      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Review & Submit",
        }),
      ).toBeVisible();

      // Verify review content
      await expect(page.getByText(proposalCategoryName)).toBeVisible();
      await expect(page.getByText("Game Master Alex")).toBeVisible();
      await expect(page.getByText(proposalTitle)).toBeVisible();
      await expect(page.getByText("An introductory RPG session for new players.")).toBeVisible();
      await expect(page.getByText("host@example.com")).toBeVisible();
      await expect(page.getByText("D&D 5e")).toBeVisible();
      await expect(page.getByText("Fantasy")).toBeVisible();

      // Submit
      await page.getByRole("button", { name: "Submit Proposal" }).click();

      // Wait for redirect after submission
      await page.waitForURL(/\/frostfire-con\//);
      await expect(page.getByRole("heading", { name: proposalTitle })).toBeVisible();

      await context.close();
    });

    test("regression: submits with min_age above 18 and unchecked required checkbox", async ({
      browser,
    }, testInfo) => {
      const suffix = testInfo.project.name;
      const regressionTitle = `Regression Run ${suffix} ${Date.now()}`;
      const statePath = path.join(__dirname, "..", ".auth-state.json");
      const storageState = JSON.parse(fs.readFileSync(statePath, "utf8"));
      const context = await browser.newContext({ storageState });
      const page = await context.newPage();

      await page.goto("/event/frostfire-con/session/propose/");
      await proposalCategoryOption(page, proposalCategoryName).click();
      await page.getByRole("button", { name: /Continue/ }).click();

      await page.locator("#id_contact_email").fill("regression@example.com");
      await page.locator(`input[name="personal_${slugify(cityName)}"]`).fill("Wroclaw");
      await page
        .locator(`select[name="personal_${slugify(experienceName)}"]`)
        .selectOption("Advanced");
      await page.getByLabel("Subscribe to newsletter?").check();
      await page.getByRole("button", { name: /Continue/ }).click();

      const slotLabels = page.locator('label:has(input[name="time_slot_ids"])');
      await slotLabels.nth(1).click();
      await page.getByRole("button", { name: /Continue/ }).click();

      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Session Details",
        }),
      ).toBeVisible();

      await page.locator("#id_title").fill(regressionTitle);
      await page
        .locator("#id_description")
        .fill("Regression coverage: min_age cap + unchecked required checkbox.");
      await page.locator("#id_participants_limit").fill("4");
      await page.locator("#id_min_age").fill("30");
      await page.locator("#id_display_name").fill("Regression GM");
      await page.locator("#id_duration").selectOption("PT2H");
      await page.locator(`input[name="session_${slugify(gameSystemName)}"]`).fill("Pathfinder");
      await page.locator(`select[name="session_${slugify(genreName)}"]`).selectOption("Fantasy");
      await page
        .locator("label", { hasText: "English" })
        .locator(`input[name="session_${slugify(languagesName)}"]`)
        .check();

      await page.getByRole("button", { name: /Continue/ }).click();

      await expect(
        page.locator("#wizard-content").getByRole("heading", {
          name: "Review & Submit",
        }),
      ).toBeVisible();
      await expect(page.getByText(regressionTitle)).toBeVisible();

      await page.getByRole("button", { name: "Submit Proposal" }).click();

      await page.waitForURL(/\/frostfire-con\//);
      await expect(page.getByText(regressionTitle)).toBeVisible();

      await context.close();
    });

    test("verifies proposal in panel proposals list and detail", async ({ page }) => {
      // Proposals list
      await page.goto("/panel/event/frostfire-con/proposals/");

      const row = page.locator("tr", {
        hasText: proposalTitle,
      });
      await expect(row).toBeVisible();
      await expect(row.getByText("Game Master Alex")).toBeVisible();
      await expect(row.getByText(proposalCategoryName)).toBeVisible();
      await expect(row.getByText("Pending")).toBeVisible();

      // Click title link → detail page
      await row
        .getByRole("link", {
          name: proposalTitle,
        })
        .click();

      // Proposal detail
      await expect(page.getByText("E2E Tester")).toBeVisible();
      await expect(page.getByText("e2e@test.local")).toBeVisible();
      await expect(page.getByText("An introductory RPG session for new players.")).toBeVisible();
      await expect(page.getByText("6", { exact: true })).toBeVisible();

      // Session fields (dt/dd pairs)
      await expect(page.getByText("D&D 5e")).toBeVisible();
      await expect(page.getByText("Fantasy")).toBeVisible();
      await expect(page.getByText("English, Polish")).toBeVisible();
      await expect(page.getByText("Yes")).toBeVisible();
    });

    test("filters proposals by session field", async ({ page }) => {
      await page.goto("/panel/event/frostfire-con/proposals/");

      const genreLabel = page.locator("label", {
        hasText: genreName,
      });
      const genreSelectId = await genreLabel.getAttribute("for");
      const genreFilter = page.locator(`#${genreSelectId}`);

      // Filter by Fantasy — the form autosubmits on change
      await genreFilter.selectOption("Fantasy");
      await page.waitForURL(/field_\d+=Fantasy/);
      await expect(
        page.getByRole("link", {
          name: proposalTitle,
        }),
      ).toBeVisible();

      // Filter by Sci-Fi — proposal should not be visible
      const genreFilterAfter = page.locator(`#${genreSelectId}`);
      await genreFilterAfter.selectOption("Sci-Fi");
      await page.waitForURL(/field_\d+=Sci-Fi/);
      await expect(
        page.getByRole("link", {
          name: proposalTitle,
        }),
      ).not.toBeVisible();

      // Clear filters
      await page.getByRole("link", { name: "Clear" }).click();
      await expect(
        page.getByRole("link", {
          name: proposalTitle,
        }),
      ).toBeVisible();
    });
  });

  // --- Reorder Tests ---

  test("reorders sibling spaces via JSON endpoint", async ({ page }) => {
    // Need >=2 top-level spaces — create a throwaway root.
    await page.goto("/panel/event/frostfire-con/venues/");
    await page.getByRole("link", { name: "New top-level space" }).click();
    await page.locator("#id_name").fill("Reorder Test Space");
    await page.getByRole("button", { name: "Create space" }).click();
    await expect(page.getByText("Space created successfully.")).toBeVisible();

    await page.goto("/panel/event/frostfire-con/venues/");

    // Top-level node ids from the root sibling list.
    const ids = await page
      .locator("#space-root-list > li.space-node")
      .evaluateAll((rows) => rows.map((r) => Number(r.getAttribute("data-space-id"))));
    expect(ids.length).toBeGreaterThanOrEqual(2);
    const reversed = [...ids].reverse();

    const csrfToken = await page.locator('input[name="csrfmiddlewaretoken"]').first().inputValue();

    // Reorder the root level (parent_pk null) via the single space endpoint.
    const status = await page.evaluate(
      async ({ order, token }) => {
        const res = await fetch("/panel/event/frostfire-con/venues/do/reorder", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": token,
          },
          body: JSON.stringify({ parent_pk: null, space_ids: order }),
        });
        return res.status;
      },
      { order: reversed, token: csrfToken },
    );
    expect(status).toBe(200);

    await page.reload();
    const newIds = await page
      .locator("#space-root-list > li.space-node")
      .evaluateAll((rows) => rows.map((r) => Number(r.getAttribute("data-space-id"))));
    expect(newIds).toEqual(reversed);

    // Clean up: delete the throwaway root.
    const menu = await openSpaceMenu(page, "Reorder Test Space");
    await menu.getByRole("button", { name: "Delete" }).click();
    await acceptConfirmModal(page);
    await expect(page.getByText("Space deleted successfully.")).toBeVisible();
  });

  // --- Time Slot Overlap Validation ---

  test("rejects overlapping time slots", async ({ page }) => {
    // Navigate to time slots page
    await page.goto("/panel/event/frostfire-con/cfp/time-slots/");

    // Extract event date from the first "Add" link
    const addLink = page
      .getByRole("link", {
        name: "Add",
        exact: true,
      })
      .first();
    const addHref = await addLink.getAttribute("href");
    const dateMatch = addHref?.match(/date=(\d{4}-\d{2}-\d{2})/);
    const dateStr = dateMatch?.[1] ?? "";

    // Get event start hour
    const startsText = await page.getByText(/Event starts at/).textContent();
    const hourMatch = startsText?.match(/starts at (\d{2}):(\d{2})/);
    const baseHour = parseInt(hourMatch?.[1] ?? "9", 10);
    const rawMin = parseInt(hourMatch?.[2] ?? "0", 10);
    const safeMin = rawMin + 1;

    // Use baseHour+3.5h offset to avoid collisions with CFP flow slots
    // (which occupy 12:01–13:31). 15-min slot, then overlap test.
    const offsetMin = 3 * 60 + 30;
    const slotStart = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin);
    const slotEnd = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 15);

    await page.goto("/panel/event/frostfire-con/cfp/time-slots/create/");
    await page.locator("#id_date").fill(slotStart.date);
    await page.locator("#id_end_date").fill(slotEnd.date);
    await page.locator("#id_start_time").fill(slotStart.time);
    await page.locator("#id_end_time").fill(slotEnd.time);
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page.getByText("Time slot created successfully.")).toBeVisible();

    // Try creating overlapping slot: offset+5 to offset+20
    // This overlaps with the first slot
    const overlapStart = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 5);
    const overlapEnd = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 20);
    await page.goto("/panel/event/frostfire-con/cfp/time-slots/create/");
    await page.locator("#id_date").fill(overlapStart.date);
    await page.locator("#id_end_date").fill(overlapEnd.date);
    await page.locator("#id_start_time").fill(overlapStart.time);
    await page.locator("#id_end_time").fill(overlapEnd.time);
    await page.getByRole("button", { name: "Create" }).click();

    // Verify error message about overlap
    await expect(page.getByText("overlaps with an existing slot")).toBeVisible();

    // Verify still on create form
    await expect(page).toHaveURL(/\/create\//);

    // Clean up: delete the first slot
    await page.goto("/panel/event/frostfire-con/cfp/time-slots/");
    // Find the slot row with the time we created
    await page
      .getByRole("button", { name: /Delete/i })
      .last()
      .click();
    await acceptConfirmModal(page);
    await expect(page.getByText("Time slot deleted successfully.")).toBeVisible();
  });

  // --- Facilitators: merge ---

  test("facilitators list exposes the merge tab and the bulk selection bar", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/facilitators/");

    // Merge has its own dedicated tab (the single merge destination).
    await expect(page.getByRole("tab", { name: "Merge", exact: true })).toBeVisible();

    // The unified bulk-triage bar is present: row checkboxes drive flag /
    // mark-guest, and "Merge selected" is a shortcut into the merge flow.
    await expect(page.getByRole("table").getByRole("checkbox").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Merge selected/ })).toBeVisible();
  });

  test("merge tab opens the merge page with an empty basket", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/facilitators/");

    await page.getByRole("tab", { name: "Merge", exact: true }).click();

    await expect(page).toHaveURL("/panel/event/frostfire-con/facilitators/merge/");

    // Search-and-collect flow: a search field, and nothing pre-selected.
    await expect(page.getByLabel("Search", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Selected for merge (0)" })).toBeVisible();
  });

  test("merge page search finds facilitators by name", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/facilitators/merge/");

    await page.getByLabel("Search", { exact: true }).fill("Alice");
    await page.getByLabel("Search", { exact: true }).press("Enter");

    // "Alice" surfaces add-able results...
    await expect(page.getByRole("button", { name: "Add" }).first()).toBeVisible();
    await expect(page.getByText(/Alice Morgan/).first()).toBeVisible();

    // ...but "Bob Chen" does not match the query.
    await expect(page.getByText("Bob Chen")).toHaveCount(0);
  });

  test("merge page merges two facilitators into a target", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/facilitators/merge/");

    // Collect two facilitators into the basket via search-and-add.
    await page.getByLabel("Search", { exact: true }).fill("Alice");
    await page.getByLabel("Search", { exact: true }).press("Enter");

    await page.getByRole("button", { name: "Add" }).first().click();
    await expect(page.getByRole("heading", { name: "Selected for merge (1)" })).toBeVisible();
    await page.getByRole("button", { name: "Add" }).first().click();
    await expect(page.getByRole("heading", { name: "Selected for merge (2)" })).toBeVisible();

    // Review, then merge with the pre-selected target and reconcile defaults.
    await page.getByRole("button", { name: "Review and merge" }).click();
    await page.getByRole("button", { name: "Merge", exact: true }).click();
    // The merge form is guarded by the confirm modal (accept button reads "Merge").
    await page.getByRole("alertdialog").getByRole("button", { name: "Merge" }).click();

    await expect(page.getByText("Facilitators merged successfully.")).toBeVisible();
    await expect(page).toHaveURL("/panel/event/frostfire-con/facilitators/");
  });

  // --- Organization announcements CRUD ---

  test("manages the announcement lifecycle and public visibility", async ({ page }) => {
    const stamp = Date.now();
    const title = `E2E Announcement ${stamp}`;
    const editedTitle = `E2E Announcement Edited ${stamp}`;
    const content = `Welcome to the convention — announcement body ${stamp}.`;

    // Create
    await page.goto("/multiverse/panel/announcements/");
    await page.getByRole("link", { name: "New announcement" }).first().click();
    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Content").fill(content);
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("Announcement created successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: title })).toBeVisible();

    // Published announcement shows on the public landing page
    await page.goto("/events/");
    await expect(page.getByRole("heading", { name: "Organization announcements" })).toBeVisible();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByText(content)).toBeVisible();

    // Edit
    await page.goto("/multiverse/panel/announcements/");
    await page
      .getByRole("row", { name: new RegExp(title) })
      .getByRole("link", { name: "Edit" })
      .click();
    await page.getByLabel("Title").fill(editedTitle);
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Announcement updated successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: editedTitle })).toBeVisible();

    // Delete via the confirmation page
    await page
      .getByRole("row", { name: new RegExp(editedTitle) })
      .getByRole("link", { name: "Delete" })
      .click();
    await expect(page.getByRole("heading", { name: "Delete announcement" })).toBeVisible();
    await page.getByRole("button", { name: "Delete" }).click();

    await expect(page.getByText("Announcement deleted successfully.")).toBeVisible();
    await expect(page.getByRole("cell", { name: editedTitle })).toBeHidden();
  });
});
