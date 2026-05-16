import fs from 'node:fs';
import path from 'node:path';

import { expect, test, type Page } from '@playwright/test';

/** Build an HH:MM string by adding minutes to a base hour:minute. */
function timeHHMM(
  hour: number,
  minute: number,
  addMinutes: number = 0,
): string {
  const d = new Date(2000, 0, 1, hour, minute + addMinutes);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
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
  const [y, m, day] = baseDateStr.split('-').map(Number);
  const d = new Date(y, m - 1, day, hour, minute + addMinutes);
  const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const ts = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return { date: ds, time: ts };
}

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

function sessionTypeRequirementSelect(page: Page, name: string) {
  return page.getByRole('combobox', { name, exact: true }).last();
}

function proposalCategoryOption(page: Page, name: string) {
  return page.getByText(name, { exact: true }).last();
}

function minutesSinceMidnight(time: string): number {
  const [hour, minute] = time.split(':').map(Number);
  return hour * 60 + minute;
}

function timeFromMinutes(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

test('panel redirects to home with message when sphere has no events', async ({
  browser,
}) => {
  const emptyBase = 'http://another.localhost:8000';

  // Use pre-built session cookie for the empty-sphere manager
  const statePath = path.join(__dirname, '..', '.auth-state-empty.json');
  const storageState = JSON.parse(fs.readFileSync(statePath, 'utf8'));
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  // Visit panel — should redirect to index (then to /events/)
  await page.goto(`${emptyBase}/panel/`);
  await expect(page).toHaveURL(`${emptyBase}/events/`);
  await expect(page.getByText('No events available')).toBeVisible();

  await context.close();
});

test.describe.configure({ mode: 'serial' });

test.describe('Backoffice Panel', () => {
  test.beforeEach(async ({ page }) => {
    // Log in via Django admin as the manager user.
    // Use domcontentloaded — the login form is interactable at DCL and
    // Firefox occasionally never fires `load` for this page, hanging the
    // default goto until the test timeout (CI run 25398374365).
    await page.goto('/admin/login/', { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Username:').fill('e2e-manager');
    await page.getByLabel('Password:').fill('e2e-manager-123');
    await page.getByRole('button', { name: /Log in/i }).click();
  });

  test('opens panel dashboard with sidebar and stats', async ({ page }) => {
    await page.goto('/panel/');

    // /panel/ redirects to the first event's dashboard
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);

    // Sidebar navigation
    await expect(page.getByRole('link', { name: /Dashboard/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Call for Proposals/ })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Proposals', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /Venues/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Event Settings/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Back to website/ })).toBeVisible();

    // Page header
    await expect(
      page.getByRole('heading', { name: 'Dashboard' }),
    ).toBeVisible();

    // Stats cards
    await expect(page.getByText('All Sessions')).toBeVisible();
    await expect(page.getByText('Program Hosts')).toBeVisible();
    await expect(page.getByText('Rooms')).toBeVisible();

    // Event selector in sidebar
    await expect(page.locator('#eventSelector')).toBeVisible();

    await page.screenshot({
      path: 'test-results/panel-dashboard.png',
      fullPage: true,
    });
  });

  // --- Step 1: Event Settings ---

  test('navigates to event settings and displays form', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/settings/');

    await expect(
      page.getByRole('heading', { name: 'Event Settings' }),
    ).toBeVisible();

    // Sidebar link active
    await expect(
      page.getByRole('link', { name: /Event Settings/ }),
    ).toBeVisible();

    // Name input pre-filled
    await expect(page.locator('#id_name')).toHaveValue('Autumn Open Playtest');

    // Save button visible
    await expect(
      page.getByRole('button', { name: 'Save Settings' }),
    ).toBeVisible();
  });

  test('updates event name via settings form', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/settings/');

    const nameInput = page.locator('#id_name');
    await nameInput.fill('Autumn Open Playtest Renamed');
    await page.getByRole('button', { name: 'Save Settings' }).click();

    // Verify success message
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();

    // Verify input shows new name
    await expect(nameInput).toHaveValue('Autumn Open Playtest Renamed');

    // Restore original name
    await nameInput.fill('Autumn Open Playtest');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();
  });

  // --- Step 2: Venues List, Create, Detail, Edit ---

  test('lists venues for the event', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/venues/');

    await expect(
      page.getByRole('cell', { name: 'Convention Center', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'New Venue' }),
    ).toBeVisible();
  });

  test('creates a new venue', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/venues/');
    await page.getByRole('link', { name: 'New Venue' }).click();

    await page.locator('#id_name').fill('Community Library');
    await page.locator('#id_address').fill('456 Book Lane');
    await page.getByRole('button', { name: 'Create Venue' }).click();

    await expect(
      page.getByText('Venue created successfully.'),
    ).toBeVisible();
    await expect(page.getByText('Community Library').first()).toBeVisible();
  });

  test('views venue detail with areas', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );

    await expect(
      page.getByRole('heading', { name: 'Convention Center' }),
    ).toBeVisible();
    await expect(page.getByText('Main Hall')).toBeVisible();
    await expect(page.getByText('Lounge')).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'New Area' }),
    ).toBeVisible();
  });

  test('edits a venue', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/edit/',
    );

    const nameInput = page.locator('#id_name');
    await expect(nameInput).toHaveValue('Convention Center');

    const addressInput = page.locator('#id_address');
    await addressInput.fill('999 Updated Avenue');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText('Venue updated successfully.'),
    ).toBeVisible();

    // Restore original address
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/edit/',
    );
    await addressInput.fill('123 Gaming Street, Tabletop City');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(
      page.getByText('Venue updated successfully.'),
    ).toBeVisible();
  });

  // --- Step 3: Venue Structure, Duplicate, Copy, Delete ---

  test('shows venue structure overview', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/structure/',
    );

    await expect(
      page.getByRole('heading', { name: 'Venue Structure' }),
    ).toBeVisible();

    await page.getByRole('link', { name: 'Convention Center', exact: true }).click();
    await expect(page).toHaveURL(/\/venues\/convention-center\/$/);
    await expect(
      page.getByRole('heading', { name: 'Convention Center' }),
    ).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Main Hall' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Lounge' })).toBeVisible();

    await page.getByRole('link', { name: 'Spaces' }).first().click();
    await expect(page.getByRole('heading', { name: 'Lounge' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Fireside Alcove' })).toBeVisible();
  });

  test('duplicates a venue', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/venues/');

    // Open dropdown for Convention Center (use exact cell match
    // to avoid also matching "Convention Center (Copy)" rows)
    const row = page
      .getByRole('row')
      .filter({
        has: page.getByRole('cell', {
          name: 'Convention Center',
          exact: true,
        }),
      });
    await row.locator('.action-dropdown-toggle').click();
    await row
      .locator('.action-dropdown-menu')
      .getByRole('link', { name: 'Duplicate' })
      .click();

    // Verify pre-filled name
    await expect(page.locator('#id_name')).toHaveValue(
      'Convention Center (Copy)',
    );

    await page
      .getByRole('button', { name: 'Duplicate Venue' })
      .click();

    await expect(
      page.getByText('Venue duplicated successfully.'),
    ).toBeVisible();
  });

  test('copies a venue to another event', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/venues/');

    // Use exact cell match to avoid matching "Convention Center (Copy)"
    const row = page
      .getByRole('row')
      .filter({
        has: page.getByRole('cell', {
          name: 'Convention Center',
          exact: true,
        }),
      });
    await row.locator('.action-dropdown-toggle').click();
    await page.getByRole('link', { name: 'Copy' }).click();

    // Select target event
    await page.locator('#id_target_event').selectOption({
      label: 'Retro Mini Jam',
    });
    await page
      .getByRole('button', { name: 'Copy to Event' })
      .click();

    await expect(
      page.getByText('Venue copied to Retro Mini Jam successfully.'),
    ).toBeVisible();
  });

  test('deletes a venue', async ({ page }) => {
    // First create a throwaway venue
    await page.goto('/panel/event/autumn-open/venues/create/');
    await page.locator('#id_name').fill('Temp Venue To Delete');
    await page.getByRole('button', { name: 'Create Venue' }).click();
    await expect(
      page.getByText('Venue created successfully.'),
    ).toBeVisible();

    // Now delete it from the venues list
    await page.goto('/panel/event/autumn-open/venues/');

    page.on('dialog', (dialog) => dialog.accept());

    await page
      .locator('tr', { hasText: 'Temp Venue To Delete' })
      .locator('.action-dropdown-toggle')
      .click();

    // The delete is a form inside the dropdown
    await page
      .locator('tr', { hasText: 'Temp Venue To Delete' })
      .locator('.action-dropdown-menu')
      .getByRole('button', { name: /Delete/i })
      .click();

    await expect(
      page.getByText('Venue deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 4: Areas CRUD ---

  test('creates an area in a venue', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );
    await page.getByRole('link', { name: 'New Area' }).click();

    await page.locator('#id_name').fill('Workshop Room');
    await page
      .locator('#id_description')
      .fill('A room for workshops');
    await page
      .getByRole('button', { name: 'Create Area' })
      .click();

    await expect(
      page.getByText('Area created successfully.'),
    ).toBeVisible();
  });

  test('views area detail with spaces', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );

    // Click "Spaces" link for Main Hall
    await page
      .locator('tr', { hasText: 'Main Hall' })
      .getByRole('link', { name: 'Spaces' })
      .click();

    await expect(
      page.getByRole('heading', { name: 'Main Hall' }),
    ).toBeVisible();
    await expect(page.getByText('East Wing')).toBeVisible();
  });

  test('edits an area', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/edit/',
    );

    const nameInput = page.locator('#id_name');
    await expect(nameInput).toHaveValue('Main Hall');

    const descInput = page.locator('#id_description');
    await descInput.fill('Updated description for main hall');
    await page
      .getByRole('button', { name: 'Save' })
      .click();

    await expect(
      page.getByText('Area updated successfully.'),
    ).toBeVisible();

    // Restore
    await page
      .locator('tr', { hasText: 'Main Hall' })
      .getByRole('link', { name: 'Edit' })
      .click();
    await descInput.fill(
      'The central gaming area with multiple tables.',
    );
    await page
      .getByRole('button', { name: 'Save' })
      .click();
    await expect(
      page.getByText('Area updated successfully.'),
    ).toBeVisible();
  });

  test('deletes an area', async ({ page }) => {
    // Create throwaway area first
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );
    await page.getByRole('link', { name: 'New Area' }).click();
    await page.locator('#id_name').fill('Temp Area To Delete');
    await page
      .getByRole('button', { name: 'Create Area' })
      .click();
    await expect(
      page.getByText('Area created successfully.'),
    ).toBeVisible();

    // Navigate back to venue detail and delete
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );

    page.on('dialog', (dialog) => dialog.accept());

    const row = page.locator('tr', {
      hasText: 'Temp Area To Delete',
    });
    await row.locator('.action-dropdown-toggle').click();
    await row
      .locator('.action-dropdown-menu')
      .getByRole('button', { name: /Delete/i })
      .click();

    await expect(
      page.getByText('Area deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 5: Spaces CRUD ---

  test('creates a space in an area', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/',
    );
    await page.getByRole('link', { name: 'New Space' }).click();

    await page.locator('#id_name').fill('North Alcove');
    await page.locator('#id_capacity').fill('15');
    await page
      .getByRole('button', { name: 'Create Space' })
      .click();

    await expect(
      page.getByText('Space created successfully.'),
    ).toBeVisible();
  });

  test('edits a space', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/spaces/east-wing/edit/',
    );

    const nameInput = page.locator('#id_name');
    await expect(nameInput).toHaveValue('East Wing');

    const capacityInput = page.locator('#id_capacity');
    await capacityInput.fill('40');
    await page
      .getByRole('button', { name: 'Save' })
      .click();

    await expect(
      page.getByText('Space updated successfully.'),
    ).toBeVisible();

    // Restore original capacity
    await page
      .locator('tr', { hasText: 'East Wing' })
      .getByRole('link', { name: 'Edit' })
      .click();
    await capacityInput.fill('30');
    await page
      .getByRole('button', { name: 'Save' })
      .click();
    await expect(
      page.getByText('Space updated successfully.'),
    ).toBeVisible();
  });

  test('deletes a space', async ({ page }) => {
    // Create throwaway space first
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/',
    );
    await page.getByRole('link', { name: 'New Space' }).click();
    await page.locator('#id_name').fill('Temp Space To Delete');
    await page
      .getByRole('button', { name: 'Create Space' })
      .click();
    await expect(
      page.getByText('Space created successfully.'),
    ).toBeVisible();

    // Delete from area detail
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/',
    );

    const row = page.locator('tr', {
      hasText: 'Temp Space To Delete',
    });
    await row.locator('.action-dropdown-toggle').click();
    await row
      .locator('.action-dropdown-menu')
      .getByRole('button', { name: /Delete/i })
      .click();

    // Confirm in the styled dialog that replaced the native confirm()
    await page
      .locator('#confirm-dialog')
      .getByRole('button', { name: 'Delete' })
      .click();

    await expect(
      page.getByText('Space deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 6: CFP Session Types ---

  test('shows CFP page and creates a session type', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/cfp/');

    await expect(
      page.getByRole('heading', { name: 'Call for Proposals' }),
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'New Session Type' }),
    ).toBeVisible();

    // Create a session type
    await page
      .getByRole('link', { name: 'New Session Type' })
      .click();
    await page.locator('#id_name').fill('Board Games');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(
      page.getByText('Session type created successfully.'),
    ).toBeVisible();
    await expect(
      page.getByRole('cell', { name: 'Board Games' }).first(),
    ).toBeVisible();
  });

  test('creates session type and navigates to configure', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/cfp/');
    await page
      .getByRole('link', { name: 'New Session Type' })
      .click();

    await page.locator('#id_name').fill('RPG Sessions');
    await page
      .getByRole('button', { name: 'Add and configure' })
      .click();

    await expect(
      page.getByText('Session type created successfully.'),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/cfp\/rpg-sessions/);
    await expect(
      page.getByRole('heading', {
        name: 'Configure Session Type',
      }),
    ).toBeVisible();
  });

  test('edits a session type', async ({ page }) => {
    // First create one to edit
    await page.goto('/panel/event/autumn-open/cfp/');
    await page
      .getByRole('link', { name: 'New Session Type' })
      .click();
    await page.locator('#id_name').fill('Workshops');
    await page
      .getByRole('button', { name: 'Add and configure' })
      .click();
    await expect(
      page.getByText('Session type created successfully.'),
    ).toBeVisible();

    // Now edit it
    await page.locator('#id_name').fill('Advanced Workshops');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText('Session type updated successfully.'),
    ).toBeVisible();
  });

  test('deletes a session type', async ({ page }) => {
    // Create one to delete
    await page.goto('/panel/event/autumn-open/cfp/');
    await page
      .getByRole('link', { name: 'New Session Type' })
      .click();
    await page.locator('#id_name').fill('Temp Type To Delete');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(
      page.getByText('Session type created successfully.'),
    ).toBeVisible();

    page.on('dialog', (dialog) => dialog.accept());

    const row = page.locator('tr', {
      hasText: 'Temp Type To Delete',
    });
    await row.getByRole('link', { name: 'Configure' }).click();

    // CFP list doesn't have dropdown — delete is on the list via
    // a form button. Go back to list and delete.
    await page.goto('/panel/event/autumn-open/cfp/');

    const listRow = page.locator('tr', {
      hasText: 'Temp Type To Delete',
    });
    await listRow
      .getByRole('button', { name: /Delete/i })
      .click();

    await expect(
      page.getByText('Session type deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 7: Fields — Personal Data & Session ---

  test('creates and manages a personal data field', async ({
    page,
  }) => {
    await page.goto(
      '/panel/event/autumn-open/cfp/personal-data/',
    );

    await expect(
      page.getByRole('heading', {
        name: 'CFP Fields',
      }),
    ).toBeVisible();

    // Create
    await page
      .getByRole('link', { name: 'New Field' })
      .click();
    await page.locator('#id_name').fill('Email');
    await page
      .locator('#id_question')
      .fill('What is your email?');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(
      page.getByText(
        'Personal data field created successfully.',
      ),
    ).toBeVisible();
    await expect(
      page.getByRole('cell', { name: 'Email' }),
    ).toBeVisible();

    // Edit
    await page
      .locator('tr', { hasText: 'Email' })
      .getByRole('link', { name: 'Edit' })
      .click();
    await page
      .locator('#id_question')
      .fill('What is your contact email?');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText(
        'Personal data field updated successfully.',
      ),
    ).toBeVisible();

    // Delete
    page.on('dialog', (dialog) => dialog.accept());
    await page
      .locator('tr', { hasText: 'Email' })
      .getByRole('button', { name: /Delete/i })
      .click();

    await expect(
      page.getByText(
        'Personal data field deleted successfully.',
      ),
    ).toBeVisible();
  });

  test('creates and manages a session field', async ({ page }, testInfo) => {
    // Suffix with retry index so retries after a half-completed attempt do
    // not collide with leftover rows and trip strict-mode locator matches.
    const retrySuffix = testInfo.retry === 0 ? '' : `-r${testInfo.retry}`;
    const fieldName = `Game System ${testInfo.project.name}${retrySuffix}`;
    await page.goto(
      '/panel/event/autumn-open/cfp/session-fields/',
    );

    await expect(
      page.getByRole('heading', { name: 'CFP Fields' }),
    ).toBeVisible();

    // Create
    await page
      .getByRole('link', { name: 'New Field' })
      .click();
    await page.locator('#id_name').fill(fieldName);
    await page
      .locator('#id_question')
      .fill('What game system?');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(
      page.getByText('Session field created successfully.'),
    ).toBeVisible();
    await expect(
      page.getByRole('cell', { name: new RegExp(fieldName) }),
    ).toBeVisible();

    // Edit
    await page
      .getByRole('row', { name: new RegExp(fieldName) })
      .getByRole('link', { name: 'Edit' })
      .click();
    await page
      .locator('#id_question')
      .fill('Which game system will you use?');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText('Session field updated successfully.'),
    ).toBeVisible();

    // Delete
    page.on('dialog', (dialog) => dialog.accept());
    await page
      .getByRole('row', { name: new RegExp(fieldName) })
      .getByRole('button', { name: /Delete/i })
      .click();

    await expect(
      page.getByText('Session field deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 8: Time Slots ---

  test('shows time slots page', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/',
    );

    await expect(
      page.getByRole('heading', { name: 'Time Slots' }),
    ).toBeVisible();
  });

  test('creates, edits, and deletes a time slot', async ({
    page,
  }, testInfo) => {
    // Navigate to time slots page and extract event start info
    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/',
    );

    // Extract date from the first per-day "Add" link's ?date= param
    const addLink = page
      .getByRole('link', {
        name: 'Add',
        exact: true,
      })
      .first();
    const addHref = await addLink.getAttribute('href');
    const dateMatch = addHref?.match(
      /date=(\d{4}-\d{2}-\d{2})/,
    );
    const dateStr = dateMatch?.[1] ?? '';

    // Extract event start hour from "Event starts at HH:MM" text
    const startsText = await page
      .getByText(/Event starts at/)
      .textContent();
    const hourMatch = startsText?.match(
      /starts at (\d{2}):(\d{2})/,
    );
    const baseHour = parseInt(hourMatch?.[1] ?? '9', 10);
    const rawMin = parseInt(hourMatch?.[2] ?? '0', 10);
    // Add 1 minute to avoid seconds-precision issue
    const safeMin = rawMin + 1;

    const bodyText = await page.locator('body').textContent();
    const ranges = [...(bodyText ?? '').matchAll(/(\d{2}):(\d{2})\s+–\s+(\d{2}):(\d{2})/g)]
      .map((match) => ({
        start: Number(match[1]) * 60 + Number(match[2]),
        end: Number(match[3]) * 60 + Number(match[4]),
      }));
    const eventStart = baseHour * 60 + safeMin;
    const eventEnd = eventStart + 239;
    const duration = 5;
    const extendedDuration = 10;
    let startMinute = eventEnd - extendedDuration;
    while (
      startMinute > eventStart &&
      ranges.some(
        (range) =>
          startMinute < range.end && startMinute + extendedDuration > range.start,
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
    await page
      .locator('#id_start_time')
      .fill(startTime);
    await page
      .locator('#id_end_time')
      .fill(endTime);
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(
      page.getByText('Time slot created successfully.'),
    ).toBeVisible();
    const createdSlot = page.getByText(`${startTime} – ${endTime}`);
    await expect(createdSlot).toBeVisible();

    // Edit
    await page
      .getByRole('link', { name: 'Edit' })
      .filter({ hasNot: page.locator('[href$="/1/edit/"]') })
      .last()
      .click();

    // Extend by 30 min
    await page
      .locator('#id_end_time')
      .fill(updatedEndTime);
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText('Time slot updated successfully.'),
    ).toBeVisible();
    await expect(
      page.getByText(`${startTime} – ${updatedEndTime}`),
    ).toBeVisible();

    // Delete
    page.on('dialog', (dialog) => dialog.accept());
    await page
      .getByRole('button', { name: /Delete/i })
      .last()
      .click();

    await expect(
      page.getByText('Time slot deleted successfully.'),
    ).toBeVisible();
  });

  // --- Step 9: Proposals & Access Control ---

  test('shows proposals page', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/proposals/',
    );

    await expect(
      page.getByRole('heading', { name: 'Proposals' }),
    ).toBeVisible();
  });

  test('non-manager user is denied panel access', async ({
    browser,
  }) => {
    // Use pre-built session cookie for regular e2e-tester
    const statePath = path.join(__dirname, '..', '.auth-state.json');
    const storageState = JSON.parse(
      fs.readFileSync(statePath, 'utf8'),
    );
    const context = await browser.newContext({ storageState });
    const page = await context.newPage();

    await page.goto('/panel/');

    // Should redirect away from panel
    await expect(page).not.toHaveURL(/\/panel\//);

    await context.close();
  });

  // --- Step 10: Full CFP → Proposal → Panel Verification ---

  test.describe.serial(
    'CFP to proposal to panel flow',
    () => {
      let proposalCategoryName = '';
      let proposalCategoryPath = '';
      let proposalTitle = '';
      let cityName = '';
      let experienceName = '';
      let newsletterName = '';
      let gameSystemName = '';
      let genreName = '';
      let languagesName = '';
      let beginnerName = '';

      test('creates session type for proposal flow', async ({
        page,
      }, testInfo) => {
        const suffix = testInfo.project.name;
        proposalCategoryName = `Tabletop RPG ${suffix}`;
        proposalTitle = `Dragon's Lair ${suffix}: A Beginner Adventure`;
        cityName = `City ${suffix}`;
        experienceName = `Experience Level ${suffix}`;
        newsletterName = `Newsletter ${suffix}`;
        gameSystemName = `Game System ${suffix}`;
        genreName = `Genre ${suffix}`;
        languagesName = `Languages ${suffix}`;
        beginnerName = `Beginner Friendly ${suffix}`;
        await page.goto(
          '/panel/event/autumn-open/cfp/create/',
        );
        await page.locator('#id_name').fill(proposalCategoryName);
        await page
          .getByRole('button', { name: 'Add and configure' })
          .click();

        await expect(
          page.getByText(
            'Session type created successfully.',
          ),
        ).toBeVisible();
        await expect(
          page.getByRole('heading', {
            name: 'Configure Session Type',
          }),
        ).toBeVisible();
        proposalCategoryPath = new URL(page.url()).pathname;
      });

      test('creates time slots for proposal flow', async ({
        page,
      }) => {
        // Get the event date from the time slots page
        await page.goto(
          '/panel/event/autumn-open/cfp/time-slots/',
        );
        const addLink = page
          .getByRole('link', {
            name: 'Add',
            exact: true,
          })
          .first();
        const addHref = await addLink.getAttribute('href');
        // Extract date from ?date= param
        const dateMatch = addHref?.match(/date=(\d{4}-\d{2}-\d{2})/);
        const dateStr = dateMatch?.[1] ?? '';

        // Compute event start hour from "Event starts at HH:MM" text
        const startsText = await page
          .getByText(/Event starts at/)
          .textContent();
        const hourMatch = startsText?.match(
          /starts at (\d{2}):(\d{2})/,
        );
        const baseHour = parseInt(hourMatch?.[1] ?? '9', 10);
        // Add 1 minute to avoid seconds-precision issue
        // (event start has seconds, form only takes HH:MM)
        const rawMin = parseInt(hourMatch?.[2] ?? '0', 10);
        const safeMin = rawMin + 1;

        // Create 3 time slots (30min each), starting 2h after event start
        // to avoid overlap with the bootstrapped 10:00–12:00 slot
        for (let i = 0; i < 3; i++) {
          const start = dateTimeAfter(dateStr, baseHour, safeMin, 120 + i * 30);
          const end = dateTimeAfter(dateStr, baseHour, safeMin, 120 + (i + 1) * 30);
          await page.goto(
            '/panel/event/autumn-open/cfp/time-slots/',
          );
          if (await page.getByText(`${start.time} – ${end.time}`).count()) continue;

          await page.goto(
            '/panel/event/autumn-open/cfp/time-slots/create/',
          );
          await page.locator('#id_date').fill(start.date);
          await page.locator('#id_end_date').fill(end.date);
          await page
            .locator('#id_start_time')
            .fill(start.time);
          await page
            .locator('#id_end_time')
            .fill(end.time);
          await page
            .getByRole('button', { name: 'Create' })
            .click();

          await expect(
            page.getByText(
              'Time slot created successfully.',
            ),
          ).toBeVisible();
        }
      });

      test('creates personal data fields for proposal flow', async ({
        page,
      }) => {
        // Field 1: City (text, required)
        await page.goto(
          '/panel/event/autumn-open/cfp/personal-data/create/',
        );
        await page.locator('#id_name').fill(cityName);
        await page
          .locator('#id_question')
          .fill('What city are you from?');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('required');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Personal data field created successfully.',
          ),
        ).toBeVisible();

        // Field 2: Experience Level (select, required)
        await page.goto(
          '/panel/event/autumn-open/cfp/personal-data/create/',
        );
        await page
          .locator('#id_name')
          .fill(experienceName);
        await page
          .locator('#id_question')
          .fill('What is your experience level?');
        await page
          .locator('#id_field_type')
          .selectOption('select');
        await expect(
          page.locator('#options-container'),
        ).toBeVisible();
        await page
          .locator('#id_options')
          .fill('Beginner\nIntermediate\nAdvanced');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('required');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Personal data field created successfully.',
          ),
        ).toBeVisible();

        // Field 3: Newsletter (checkbox, optional)
        await page.goto(
          '/panel/event/autumn-open/cfp/personal-data/create/',
        );
        await page.locator('#id_name').fill(newsletterName);
        await page
          .locator('#id_question')
          .fill('Subscribe to newsletter?');
        await page
          .locator('#id_field_type')
          .selectOption('checkbox');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('optional');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Personal data field created successfully.',
          ),
        ).toBeVisible();
      });

      test('creates session fields for proposal flow', async ({
        page,
      }) => {
        // Field 1: Game System (text, required)
        await page.goto(
          '/panel/event/autumn-open/cfp/session-fields/create/',
        );
        await page.locator('#id_name').fill(gameSystemName);
        await page
          .locator('#id_question')
          .fill('What game system will you use?');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('required');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Session field created successfully.',
          ),
        ).toBeVisible();

        // Field 2: Genre (select, required)
        await page.goto(
          '/panel/event/autumn-open/cfp/session-fields/create/',
        );
        await page.locator('#id_name').fill(genreName);
        await page
          .locator('#id_question')
          .fill('What genre is your session?');
        await page
          .locator('#id_field_type')
          .selectOption('select');
        await expect(
          page.locator('#options-container'),
        ).toBeVisible();
        await page
          .locator('#id_options')
          .fill('Fantasy\nSci-Fi\nHorror');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('required');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Session field created successfully.',
          ),
        ).toBeVisible();

        // Field 3: Languages (select multiple, optional)
        await page.goto(
          '/panel/event/autumn-open/cfp/session-fields/create/',
        );
        await page.locator('#id_name').fill(languagesName);
        await page
          .locator('#id_question')
          .fill('Which languages can you run in?');
        await page
          .locator('#id_field_type')
          .selectOption('select');
        await expect(
          page.locator('#options-container'),
        ).toBeVisible();
        await page
          .locator('#id_options')
          .fill('English\nPolish\nGerman');
        await page.locator('#id_is_multiple').check();
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('optional');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Session field created successfully.',
          ),
        ).toBeVisible();

        // Field 4: Beginner Friendly (checkbox, optional)
        await page.goto(
          '/panel/event/autumn-open/cfp/session-fields/create/',
        );
        await page
          .locator('#id_name')
          .fill(beginnerName);
        await page
          .locator('#id_question')
          .fill('Is this session beginner-friendly?');
        await page
          .locator('#id_field_type')
          .selectOption('checkbox');
        await sessionTypeRequirementSelect(page, proposalCategoryName)
          .selectOption('optional');
        await page
          .getByRole('button', { name: 'Create' })
          .click();
        await expect(
          page.getByText(
            'Session field created successfully.',
          ),
        ).toBeVisible();
      });

      test('configures session type with all fields and time slots', async ({
        page,
      }) => {
        await page.goto(proposalCategoryPath);

        // Set submission window (past to future)
        const now = new Date();
        const yesterday = new Date(
          now.getTime() - 24 * 60 * 60 * 1000,
        );
        const nextWeek = new Date(
          now.getTime() + 7 * 24 * 60 * 60 * 1000,
        );
        const toLocalISO = (d: Date) =>
          d.getFullYear() +
          '-' +
          String(d.getMonth() + 1).padStart(2, '0') +
          '-' +
          String(d.getDate()).padStart(2, '0') +
          'T' +
          String(d.getHours()).padStart(2, '0') +
          ':' +
          String(d.getMinutes()).padStart(2, '0');
        await page
          .locator('#id_start_time')
          .fill(toLocalISO(yesterday));
        await page
          .locator('#id_end_time')
          .fill(toLocalISO(nextWeek));

        const ensureChosen = async (group: string, fieldName: string) => {
          const chosen = page.locator(`${group} .chosen-list .field-item`, {
            hasText: fieldName,
          });
          if ((await chosen.count()) === 0) {
            await page
              .locator(`${group} .avail-list .field-item`, {
                hasText: fieldName,
              })
              .locator('.add-field')
              .click();
          }
          await expect(chosen).toBeVisible();
        };

        for (const fieldName of [cityName, experienceName, newsletterName]) {
          await ensureChosen('#host-fields-list', fieldName);
        }

        for (const fieldName of [
          gameSystemName,
          genreName,
          languagesName,
          beginnerName,
        ]) {
          await ensureChosen('#session-fields-list', fieldName);
        }

        // Add all time slots
        const slotAvail = page.locator(
          '#time-slots-list .avail-list .field-item',
        );
        while ((await slotAvail.count()) > 0) {
          await slotAvail
            .first()
            .locator('.add-field')
            .click();
        }

        // Add a duration: 2h 0min
        await page.locator('#duration-hours').fill('2');
        await page.locator('#duration-minutes').fill('0');
        await page.locator('#add-duration-btn').click();
        await expect(
          page.locator('.duration-item', { hasText: '2h' }),
        ).toBeVisible();

        // Save
        await page
          .getByRole('button', { name: 'Save' })
          .click();

        await expect(
          page.getByText(
            'Session type updated successfully.',
          ),
        ).toBeVisible();
      });

      test('submits a proposal through the public wizard', async ({
        browser,
      }) => {
        // Use a separate browser context with the e2e-tester user
        const statePath = path.join(__dirname, '..', '.auth-state.json');
        const storageState = JSON.parse(
          fs.readFileSync(statePath, 'utf8'),
        );
        const context = await browser.newContext({
          storageState,
        });
        const page = await context.newPage();

        // Step 1: Category
        await page.goto(
          '/chronology/event/autumn-open/session/propose/',
        );
        await proposalCategoryOption(page, proposalCategoryName).click();
        await page
          .getByRole('button', { name: /Continue/ })
          .click();

        // Step 2: Personal Data
        await expect(
          page.locator('#wizard-content').getByRole('heading', {
            name: 'Your Information',
          }),
        ).toBeVisible();

        await page
          .locator('#id_contact_email')
          .fill('host@example.com');
        await page
          .locator(`input[name="personal_${slugify(cityName)}"]`)
          .fill('Krakow');
        await page
          .locator(`select[name="personal_${slugify(experienceName)}"]`)
          .selectOption('Intermediate');
        await page
          .getByLabel('Subscribe to newsletter?')
          .check();
        await page
          .getByRole('button', { name: /Continue/ })
          .click();

        // Step 3: Time Slots
        await expect(
          page.locator('#wizard-content').getByRole('heading', {
            name: 'Preferred Time Slots',
          }),
        ).toBeVisible();

        // Check 1st and 3rd slot
        const slotLabels = page.locator(
          'label:has(input[name="time_slot_ids"])',
        );
        await slotLabels.nth(0).click();
        await slotLabels.nth(2).click();
        await page
          .getByRole('button', { name: /Continue/ })
          .click();

        // Step 4: Session Details
        await expect(
          page.locator('#wizard-content').getByRole('heading', {
            name: 'Session Details',
          }),
        ).toBeVisible();

        await page
          .locator('#id_title')
          .fill(proposalTitle);
        await page
          .locator('#id_description')
          .fill(
            'An introductory RPG session for new players.',
          );
        await page
          .locator('#id_participants_limit')
          .fill('6');
        await page
          .locator('#id_display_name')
          .fill('Game Master Alex');
        await page
          .locator('#id_duration')
          .selectOption('PT2H');
        await page
          .locator(`input[name="session_${slugify(gameSystemName)}"]`)
          .fill('D&D 5e');
        await page
          .locator(`select[name="session_${slugify(genreName)}"]`)
          .selectOption('Fantasy');
        await page
          .locator('label', { hasText: 'English' })
          .locator(`input[name="session_${slugify(languagesName)}"]`)
          .check();
        await page
          .locator('label', { hasText: 'Polish' })
          .locator(`input[name="session_${slugify(languagesName)}"]`)
          .check();
        await page
          .locator(`input[name="session_${slugify(beginnerName)}"]`)
          .check();
        await page
          .getByRole('button', { name: /Continue/ })
          .click();

        // Step 5: Review & Submit
        await expect(
          page.locator('#wizard-content').getByRole('heading', {
            name: 'Review & Submit',
          }),
        ).toBeVisible();

        // Verify review content
        await expect(
          page.getByText(proposalCategoryName),
        ).toBeVisible();
        await expect(
          page.getByText('Game Master Alex'),
        ).toBeVisible();
        await expect(
          page.getByText(proposalTitle),
        ).toBeVisible();
        await expect(
          page.getByText(
            'An introductory RPG session for new players.',
          ),
        ).toBeVisible();
        await expect(
          page.getByText('host@example.com'),
        ).toBeVisible();
        await expect(page.getByText('D&D 5e')).toBeVisible();
        await expect(
          page.getByText('Fantasy'),
        ).toBeVisible();

        // Submit
        await page
          .getByRole('button', { name: 'Submit Proposal' })
          .click();

        // Wait for redirect after submission
        await page.waitForURL(/\/autumn-open\//);
        await expect(
          page.getByText(proposalTitle),
        ).toBeVisible();

        await context.close();
      });

      test('verifies proposal in panel proposals list and detail', async ({
        page,
      }) => {
        // Proposals list
        await page.goto(
          '/panel/event/autumn-open/proposals/',
        );

        const row = page.locator('tr', {
          hasText: proposalTitle,
        });
        await expect(row).toBeVisible();
        await expect(
          row.getByText('Game Master Alex'),
        ).toBeVisible();
        await expect(
          row.getByText(proposalCategoryName),
        ).toBeVisible();
        await expect(row.getByText('Pending')).toBeVisible();

        // Click title link → detail page
        await row
          .getByRole('link', {
            name: proposalTitle,
          })
          .click();

        // Proposal detail
        await expect(
          page.getByText('E2E Tester'),
        ).toBeVisible();
        await expect(
          page.getByText('e2e@test.local'),
        ).toBeVisible();
        await expect(
          page.getByText(
            'An introductory RPG session for new players.',
          ),
        ).toBeVisible();
        await expect(
          page.getByText('6', { exact: true }),
        ).toBeVisible();

        // Session fields (dt/dd pairs)
        await expect(page.getByText('D&D 5e')).toBeVisible();
        await expect(
          page.getByText('Fantasy'),
        ).toBeVisible();
        await expect(
          page.getByText('English, Polish'),
        ).toBeVisible();
        await expect(page.getByText('Yes')).toBeVisible();
      });

      test('filters proposals by session field', async ({
        page,
      }) => {
        await page.goto(
          '/panel/event/autumn-open/proposals/',
        );

        const genreSelect = page.locator(
          'select[name^="field_"]',
        );
        const genreLabel = page.locator('label', {
          hasText: genreName,
        });
        const genreSelectId =
          await genreLabel.getAttribute('for');
        const genreFilter = page.locator(
          `#${genreSelectId}`,
        );

        // Filter by Fantasy — proposal should be visible
        await genreFilter.selectOption('Fantasy');
        await page
          .getByRole('button', { name: 'Filter' })
          .click();
        await expect(
          page.getByRole('link', {
            name: proposalTitle,
          }),
        ).toBeVisible();

        // Filter by Sci-Fi — proposal should not be visible
        const genreFilterAfter = page.locator(
          `#${genreSelectId}`,
        );
        await genreFilterAfter.selectOption('Sci-Fi');
        await page
          .getByRole('button', { name: 'Filter' })
          .click();
        await expect(
          page.getByRole('link', {
            name: proposalTitle,
          }),
        ).not.toBeVisible();

        // Clear filters
        await page
          .getByRole('link', { name: 'Clear' })
          .click();
        await expect(
          page.getByRole('link', {
            name: proposalTitle,
          }),
        ).toBeVisible();
      });
    },
  );

  // --- Reorder Tests ---

  test('reorders venues via JSON endpoint', async ({
    page,
  }) => {
    // Create a second venue for reordering
    await page.goto(
      '/panel/event/autumn-open/venues/create/',
    );
    await page.locator('#id_name').fill('Reorder Test Venue');
    await page
      .locator('#id_address')
      .fill('123 Reorder St');
    await page
      .getByRole('button', { name: 'Create Venue' })
      .click();
    await expect(
      page.getByText('Venue created successfully.'),
    ).toBeVisible();

    // Navigate to venues page
    await page.goto('/panel/event/autumn-open/venues/');

    // Extract venue IDs from data-venue-id attributes
    const venueIds = await page
      .locator('.venue-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-venue-id'))),
      );
    expect(venueIds.length).toBeGreaterThanOrEqual(2);

    // Reverse the order
    const reversed = [...venueIds].reverse();

    // Extract CSRF token from the delete form on the page
    const csrfToken = await page
      .locator(
        'input[name="csrfmiddlewaretoken"]',
      )
      .first()
      .inputValue();

    // Call reorder endpoint via fetch
    const response = await page.evaluate(
      async ({ ids, token }) => {
        const res = await fetch(
          '/panel/event/autumn-open/venues/do/reorder',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': token,
            },
            body: JSON.stringify({ venue_ids: ids }),
          },
        );
        return res.status;
      },
      { ids: reversed, token: csrfToken },
    );
    expect(response).toBe(200);

    // Reload and verify order changed
    await page.reload();
    const newIds = await page
      .locator('.venue-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-venue-id'))),
      );
    expect(newIds).toEqual(reversed);

    // Clean up: delete "Reorder Test Venue"
    page.on('dialog', (dialog) => dialog.accept());
    await page
      .locator('tr', { hasText: 'Reorder Test Venue' })
      .locator('.action-dropdown-toggle')
      .click();
    await page
      .locator('tr', { hasText: 'Reorder Test Venue' })
      .locator('.action-dropdown-menu')
      .getByRole('button', { name: /Delete/i })
      .click();
    await expect(
      page.getByText('Venue deleted successfully.'),
    ).toBeVisible();
  });

  test('reorders areas via JSON endpoint', async ({
    page,
  }) => {
    // Convention Center has Main Hall and Lounge
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/',
    );

    // Extract area IDs
    const areaIds = await page
      .locator('.area-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-area-id'))),
      );
    expect(areaIds.length).toBeGreaterThanOrEqual(2);

    // Reverse the order
    const reversed = [...areaIds].reverse();

    // Extract CSRF token from a form on the page
    const csrfToken = await page
      .locator(
        'input[name="csrfmiddlewaretoken"]',
      )
      .first()
      .inputValue();

    // Call reorder endpoint
    const response = await page.evaluate(
      async ({ ids, token }) => {
        const res = await fetch(
          '/panel/event/autumn-open/venues/convention-center/areas/do/reorder',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': token,
            },
            body: JSON.stringify({ area_ids: ids }),
          },
        );
        return res.status;
      },
      { ids: reversed, token: csrfToken },
    );
    expect(response).toBe(200);

    // Reload and verify order changed
    await page.reload();
    const newIds = await page
      .locator('.area-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-area-id'))),
      );
    expect(newIds).toEqual(reversed);

    // Restore original order
    await page.evaluate(
      async ({ ids, token }) => {
        await fetch(
          '/panel/event/autumn-open/venues/convention-center/areas/do/reorder',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': token,
            },
            body: JSON.stringify({ area_ids: ids }),
          },
        );
      },
      { ids: areaIds, token: csrfToken },
    );
  });

  test('reorders spaces via JSON endpoint', async ({
    page,
  }) => {
    // Create a second space in Main Hall for reordering
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/',
    );
    await page
      .getByRole('link', { name: 'New Space' })
      .click();
    await page
      .locator('#id_name')
      .fill('Reorder Test Space');
    await page.locator('#id_capacity').fill('10');
    await page
      .getByRole('button', { name: 'Create Space' })
      .click();
    await expect(
      page.getByText('Space created successfully.'),
    ).toBeVisible();

    // Navigate back to area detail
    await page.goto(
      '/panel/event/autumn-open/venues/convention-center/areas/main-hall/',
    );

    // Extract space IDs
    const spaceIds = await page
      .locator('.space-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-space-id'))),
      );
    expect(spaceIds.length).toBeGreaterThanOrEqual(2);

    // Reverse the order
    const reversed = [...spaceIds].reverse();

    // Extract CSRF token from a form on the page
    const csrfToken = await page
      .locator(
        'input[name="csrfmiddlewaretoken"]',
      )
      .first()
      .inputValue();

    // Call reorder endpoint
    const response = await page.evaluate(
      async ({ ids, token }) => {
        const res = await fetch(
          '/panel/event/autumn-open/venues/convention-center/areas/main-hall/spaces/do/reorder',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': token,
            },
            body: JSON.stringify({ space_ids: ids }),
          },
        );
        return res.status;
      },
      { ids: reversed, token: csrfToken },
    );
    expect(response).toBe(200);

    // Reload and verify order changed
    await page.reload();
    const newIds = await page
      .locator('.space-row')
      .evaluateAll((rows) =>
        rows.map((r) => Number(r.getAttribute('data-space-id'))),
      );
    expect(newIds).toEqual(reversed);

    // Clean up: delete "Reorder Test Space"
    const reorderRow = page.locator('tr', {
      hasText: 'Reorder Test Space',
    });
    await reorderRow
      .locator('.action-dropdown-toggle')
      .click();
    await reorderRow
      .locator('.action-dropdown-menu')
      .getByRole('button', { name: /Delete/i })
      .click();

    // Confirm in the styled dialog that replaced the native confirm()
    await page
      .locator('#confirm-dialog')
      .getByRole('button', { name: 'Delete' })
      .click();

    await expect(
      page.getByText('Space deleted successfully.'),
    ).toBeVisible();
  });

  // --- Time Slot Overlap Validation ---

  test('rejects overlapping time slots', async ({
    page,
  }) => {
    // Navigate to time slots page
    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/',
    );

    // Extract event date from the first "Add" link
    const addLink = page
      .getByRole('link', {
        name: 'Add',
        exact: true,
      })
      .first();
    const addHref = await addLink.getAttribute('href');
    const dateMatch = addHref?.match(
      /date=(\d{4}-\d{2}-\d{2})/,
    );
    const dateStr = dateMatch?.[1] ?? '';

    // Get event start hour
    const startsText = await page
      .getByText(/Event starts at/)
      .textContent();
    const hourMatch = startsText?.match(
      /starts at (\d{2}):(\d{2})/,
    );
    const baseHour = parseInt(hourMatch?.[1] ?? '9', 10);
    const rawMin = parseInt(hourMatch?.[2] ?? '0', 10);
    const safeMin = rawMin + 1;

    // Use baseHour+3.5h offset to avoid collisions with CFP flow slots
    // (which occupy 12:01–13:31). 15-min slot, then overlap test.
    const offsetMin = 3 * 60 + 30;
    const slotStart = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin);
    const slotEnd = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 15);

    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/create/',
    );
    await page.locator('#id_date').fill(slotStart.date);
    await page.locator('#id_end_date').fill(slotEnd.date);
    await page
      .locator('#id_start_time')
      .fill(slotStart.time);
    await page
      .locator('#id_end_time')
      .fill(slotEnd.time);
    await page
      .getByRole('button', { name: 'Create' })
      .click();
    await expect(
      page.getByText('Time slot created successfully.'),
    ).toBeVisible();

    // Try creating overlapping slot: offset+5 to offset+20
    // This overlaps with the first slot
    const overlapStart = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 5);
    const overlapEnd = dateTimeAfter(dateStr, baseHour, safeMin, offsetMin + 20);
    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/create/',
    );
    await page.locator('#id_date').fill(overlapStart.date);
    await page.locator('#id_end_date').fill(overlapEnd.date);
    await page
      .locator('#id_start_time')
      .fill(overlapStart.time);
    await page
      .locator('#id_end_time')
      .fill(overlapEnd.time);
    await page
      .getByRole('button', { name: 'Create' })
      .click();

    // Verify error message about overlap
    await expect(
      page.getByText('overlaps with an existing slot'),
    ).toBeVisible();

    // Verify still on create form
    await expect(page).toHaveURL(/\/create\//);

    // Clean up: delete the first slot
    await page.goto(
      '/panel/event/autumn-open/cfp/time-slots/',
    );
    page.on('dialog', (dialog) => dialog.accept());
    // Find the slot row with the time we created
    await page
      .getByRole('button', { name: /Delete/i })
      .last()
      .click();
    await expect(
      page.getByText('Time slot deleted successfully.'),
    ).toBeVisible();
  });

  // --- Facilitators: merge ---

  test('facilitators list shows always-enabled merge view button and disabled merge selected', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/facilitators/');

    // "Merge view" is a plain link — always accessible
    await expect(
      page.getByRole('link', { name: /Merge view/ }),
    ).toBeVisible();

    // "Merge selected" starts disabled
    await expect(
      page.getByRole('button', { name: /Merge selected/ }),
    ).toBeDisabled();
  });

  test('merge selected button enables after checking 2+ facilitators', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/facilitators/');

    const mergeSelectedBtn = page.getByRole('button', {
      name: /Merge selected/,
    });

    // One checkbox checked — still disabled
    await page.locator('.facilitator-checkbox').first().check();
    await expect(mergeSelectedBtn).toBeDisabled();

    // Two checkboxes checked — now enabled
    await page.locator('.facilitator-checkbox').nth(1).check();
    await expect(mergeSelectedBtn).not.toBeDisabled();
  });

  test('merge view button opens merge page with no pre-selection', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/facilitators/');

    await page.getByRole('link', { name: /Merge view/ }).click();

    await expect(page).toHaveURL(
      '/panel/event/autumn-open/facilitators/merge/',
    );

    // Search field is present
    await expect(page.locator('#facilitator-search')).toBeVisible();

    // All facilitator checkboxes are unchecked
    const checkboxes = page.locator('.facilitator-checkbox');
    const count = await checkboxes.count();
    expect(count).toBeGreaterThanOrEqual(2);
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked();
    }
  });

  test('merge selected passes preselected ids to merge page', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/facilitators/');

    const facilitatorRows = page
      .getByRole('row')
      .filter({ has: page.getByRole('link', { name: /.+/ }) });
    await expect(facilitatorRows.first()).toBeVisible();
    await expect(facilitatorRows.nth(1)).toBeVisible();

    const firstName = (await facilitatorRows.nth(0).getByRole('link').first().textContent())?.trim();
    const secondName = (await facilitatorRows.nth(1).getByRole('link').first().textContent())?.trim();
    expect(firstName).toBeTruthy();
    expect(secondName).toBeTruthy();

    await facilitatorRows.nth(0).getByRole('checkbox').check();
    await facilitatorRows.nth(1).getByRole('checkbox').check();

    await page
      .getByRole('button', { name: /Merge selected/ })
      .click();

    await expect(page).toHaveURL(/\/facilitators\/merge\/\?ids=/);

    await expect(page.getByLabel(firstName!, { exact: true })).toBeChecked();
    await expect(page.getByLabel(secondName!, { exact: true })).toBeChecked();
  });

  test('merge page search filters facilitators by name', async ({ page }) => {
    await page.goto(
      '/panel/event/autumn-open/facilitators/merge/',
    );

    await page.locator('#facilitator-search').fill('Alice');

    // Matching rows remain visible
    await expect(
      page
        .locator('.facilitator-row')
        .filter({ has: page.locator('label', { hasText: /Alice/ }) })
        .first(),
    ).toBeVisible();

    // Bob Chen row is hidden
    await expect(
      page.locator('.facilitator-row').filter({ hasText: 'Bob Chen' }),
    ).toBeHidden();
  });

  test('merge page merges selected facilitators into target', async ({
    page,
  }) => {
    await page.goto(
      '/panel/event/autumn-open/facilitators/merge/',
    );

    const rows = page.locator('.facilitator-row');
    await expect(rows.first()).toBeVisible();
    await expect(rows.nth(1)).toBeVisible();

    const firstName = (await rows.nth(0).locator('label').textContent())?.trim();
    const secondName = (await rows.nth(1).locator('label').textContent())?.trim();
    expect(firstName).toBeTruthy();
    expect(secondName).toBeTruthy();

    await page.getByLabel(firstName!, { exact: true }).check();
    await page.getByLabel(secondName!, { exact: true }).check();
    await rows.nth(0).locator('input[name="target_id"]').check();

    await page.getByRole('button', { name: /Merge/ }).click();

    await expect(
      page.getByText('Facilitators merged successfully.'),
    ).toBeVisible();
    await expect(page).toHaveURL(
      '/panel/event/autumn-open/facilitators/',
    );

    await expect(page.getByText(secondName!)).not.toBeVisible();
    await expect(page.getByRole('cell', { name: firstName!, exact: true })).toBeVisible();
  });
});
