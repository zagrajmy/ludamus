import { expect, test } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

test.describe('Timetable', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin/login/');
    await page.getByLabel('Username:').fill('e2e-manager');
    await page.getByLabel('Password:').fill('e2e-manager-123');
    await page.getByRole('button', { name: /Log in/i }).click();
  });

  // --- Page Loading ---

  test('opens timetable page with grid and session list', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.getByRole('heading', { name: 'Schedule' }),
    ).toBeVisible();

    // Session list panel
    await expect(
      page.getByText('Sessions to assign'),
    ).toBeVisible();

    // Grid area exists
    await expect(page.locator('#timetable-grid')).toBeVisible();

    // Conflict panel (shows "All clear" or "N conflict(s)")
    await expect(page.locator('#conflicts-fold')).toBeVisible();

    await page.screenshot({
      path: 'test-results/timetable-page.png',
      fullPage: true,
    });
  });

  test('session list loads via HTMX and shows unscheduled sessions', async ({
    page,
  }) => {
    const sessionListLoaded = page.waitForResponse(
      (r) => r.url().includes('/parts/sessions/') && r.status() === 200,
    );
    await page.goto('/panel/event/sunhaven-festival/timetable/');
    await sessionListLoaded;

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible();

    await expect(
      page.locator('#session-list').getByText('Dungeon Crawl'),
    ).toBeVisible();

    await expect(
      page.locator('#session-list').getByText('Storytelling Workshop'),
    ).toBeVisible();
  });

  // --- Session Search ---

  test('search filters session list', async ({ page }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Wait for initial load — all 3 sessions visible
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.locator('#session-list').getByText('Storytelling Workshop'),
    ).toBeVisible();

    // Type search term — use pressSequentially so keyup events fire
    // (HTMX listens for keyup, which .fill() does not trigger)
    const searchInput = page.locator('input[name="search"]');
    await searchInput.click();
    await searchInput.pressSequentially('Dungeon', { delay: 30 });

    // Wait for Storytelling Workshop to disappear, confirming
    // the HTMX swap with filtered results has completed.
    await expect(
      page.locator('#session-list').getByText('Storytelling Workshop'),
    ).not.toBeVisible({ timeout: 10000 });

    // Only Dungeon Crawl should remain
    await expect(
      page.locator('#session-list').getByText('Dungeon Crawl'),
    ).toBeVisible();

    // Other sessions should be filtered out
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).not.toBeVisible();

    await expect(
      page.locator('#session-list').getByText('Storytelling Workshop'),
    ).not.toBeVisible();
  });

  // --- Session Detail (Left Pane) ---

  test('clicking a session card opens the detail view', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Wait for session list
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Click the session card
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    // Left pane should swap to detail view
    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });
    await expect(
      leftPane.getByText('RPG Introduction'),
    ).toBeVisible();
    await expect(
      leftPane.getByText('Not assigned'),
    ).toBeVisible();

    // Assign button should be present
    await expect(
      leftPane.getByRole('button', { name: 'Assign' }),
    ).toBeVisible();
  });

  test('back button returns to session list', async ({ page }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Open detail view
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    // Click Back
    await leftPane.getByText('Back').click();

    // Session list should reappear
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 5000 });
  });

  // --- Assignment Mode ---

  test('clicking Assign enters assignment mode with banner', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Open detail view
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    // Click Assign
    await leftPane
      .getByRole('button', { name: 'Assign' })
      .click();

    // Banner should appear
    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);
    await expect(
      page.getByText('Click a position on the grid'),
    ).toBeVisible();

    // Grid columns should have assignment mode class
    await expect(
      page.locator('.timetable-column.assign-mode-active').first(),
    ).toBeVisible();
  });

  test('Escape key cancels assignment mode', async ({ page }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Enter assignment mode
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    await leftPane
      .getByRole('button', { name: 'Assign' })
      .click();

    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);

    // Press Escape
    await page.keyboard.press('Escape');

    // Banner should hide
    await expect(page.locator('#assign-mode-banner')).toHaveClass(
      /hidden/,
    );

    // Columns should lose assignment mode
    await expect(
      page.locator('.timetable-column.assign-mode-active'),
    ).toHaveCount(0);
  });

  test('cancel button exits assignment mode', async ({ page }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Enter assignment mode
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    await leftPane
      .getByRole('button', { name: 'Assign' })
      .click();

    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);

    // Click cancel button
    await page.locator('#assign-mode-cancel').click();

    // Banner should hide
    await expect(page.locator('#assign-mode-banner')).toHaveClass(
      /hidden/,
    );
  });

  // --- Assign and Unassign Flow ---

  test('assigns a session by clicking grid column', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Enter assignment mode for RPG Introduction
    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'RPG Introduction',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    await leftPane
      .getByRole('button', { name: 'Assign' })
      .click();

    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);

    // Click on first grid column near the top (to assign at event start)
    const column = page
      .locator('.timetable-column.assign-mode-active')
      .first();
    await column.click({ position: { x: 50, y: 30 } });

    // Banner should disappear after assignment
    await expect(page.locator('#assign-mode-banner')).toHaveClass(
      /hidden/,
      { timeout: 5000 },
    );

    // Wait for grid refresh — session should now appear in grid
    await expect(
      page
        .locator('#timetable-grid')
        .getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Session should disappear from unscheduled list
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).not.toBeVisible({ timeout: 10000 });
  });

  test('clicking scheduled session in grid shows Unassign button', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Wait for grid to show the assigned session
    const gridSession = page
      .locator('#timetable-grid')
      .getByText('RPG Introduction');
    await expect(gridSession).toBeVisible({ timeout: 10000 });

    // Click the session in the grid
    await gridSession.click();

    // Left pane should show detail with Unassign button
    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });
    await expect(
      leftPane.getByRole('button', { name: 'Unassign' }),
    ).toBeVisible();
  });

  test('unassigns a session', async ({ page }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Click the assigned session in grid
    const gridSession = page
      .locator('#timetable-grid')
      .getByText('RPG Introduction');
    await expect(gridSession).toBeVisible({ timeout: 10000 });
    await gridSession.click();

    // Click Unassign
    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByRole('button', { name: 'Unassign' }),
    ).toBeVisible({ timeout: 5000 });
    await leftPane
      .getByRole('button', { name: 'Unassign' })
      .click();

    // Session should reappear in unscheduled list
    await expect(
      page.locator('#session-list').getByText('RPG Introduction'),
    ).toBeVisible({ timeout: 10000 });

    // Session should be gone from grid
    await expect(
      page
        .locator('#timetable-grid')
        .getByText('RPG Introduction'),
    ).not.toBeVisible({ timeout: 5000 });
  });

  // --- Confirm / Unconfirm Flow ---

  test('confirms and unconfirms a scheduled session', async ({
    page,
  }) => {
    // Assign "Storytelling Workshop" so a scheduled item exists. Auto-confirm
    // is on by default, so the freshly scheduled item starts confirmed.
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await page
      .locator('#session-list')
      .locator('[data-session-pk]', {
        hasText: 'Storytelling Workshop',
      })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    await leftPane.getByRole('button', { name: 'Assign' }).click();
    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);

    await page
      .locator('.timetable-column.assign-mode-active')
      .first()
      .click({ position: { x: 50, y: 30 } });

    await expect(page.locator('#assign-mode-banner')).toHaveClass(
      /hidden/,
      { timeout: 5000 },
    );

    // Open the scheduled item's detail pane from the grid.
    const gridSession = page
      .locator('#timetable-grid')
      .getByText('Storytelling Workshop');
    await expect(gridSession).toBeVisible({ timeout: 10000 });
    await gridSession.click();

    await expect(
      leftPane.getByRole('button', {
        name: 'Undo confirmation',
      }),
    ).toBeVisible({ timeout: 5000 });

    // Undo — the button flips to the "Confirm program item" state.
    await leftPane
      .getByRole('button', { name: 'Undo confirmation' })
      .click();
    await expect(
      leftPane.getByRole('button', { name: 'Confirm program item' }),
    ).toBeVisible({ timeout: 5000 });

    // Confirm again — the button returns to the "Undo confirmation" state.
    await leftPane
      .getByRole('button', { name: 'Confirm program item' })
      .click();
    await expect(
      leftPane.getByRole('button', {
        name: 'Undo confirmation',
      }),
    ).toBeVisible({ timeout: 5000 });

    // Restore shared seed state: unassign so "Storytelling Workshop" returns
    // to the unscheduled list. The suite runs serially against a persistent
    // DB reused across browser projects, so every assign must be undone.
    await leftPane.getByRole('button', { name: 'Unassign' }).click();
    await expect(
      page.locator('#session-list').getByText('Storytelling Workshop'),
    ).toBeVisible({ timeout: 10000 });
  });

  // --- Conflict Panel ---

  test('conflict panel loads and shows conflict status', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Wait for the conflict panel HTMX load — it shows either "All clear" or a
    // conflict count. The fold only auto-opens when there ARE conflicts, so on
    // a clean grid the status sits in a collapsed <details>; assert the panel
    // loaded its status (textContent) rather than requiring it to be visible.
    await expect(page.locator('#conflict-panel')).toContainText(
      /All clear|conflict/,
      { timeout: 10000 },
    );
  });

  // --- Activity Log ---

  test('activity log page loads and shows tab navigation', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/log/');

    await expect(
      page.getByRole('heading', {
        name: 'Schedule Activity Log',
      }),
    ).toBeVisible();

    // Tab navigation
    await expect(
      page.getByRole('tab', { name: 'Activity Log' }),
    ).toBeVisible();
  });

  // --- Revert (latest-change-only) ---

  test('activity log offers Revert only on the latest change per session', async ({
    page,
  }) => {
    // Assign "Dungeon Crawl" so it gets a fresh assign entry in the log.
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    await page
      .locator('#session-list')
      .locator('[data-session-pk]', { hasText: 'Dungeon Crawl' })
      .click();

    const leftPane = page.locator('#left-pane');
    await expect(
      leftPane.getByText('Session details'),
    ).toBeVisible({ timeout: 5000 });

    await leftPane.getByRole('button', { name: 'Assign' }).click();
    await expect(
      page.locator('#assign-mode-banner'),
    ).not.toHaveClass(/hidden/);

    await page
      .locator('.timetable-column.assign-mode-active')
      .first()
      .click({ position: { x: 50, y: 30 } });

    await expect(page.locator('#assign-mode-banner')).toHaveClass(
      /hidden/,
      { timeout: 5000 },
    );
    await expect(
      page.locator('#timetable-grid').getByText('Dungeon Crawl'),
    ).toBeVisible({ timeout: 10000 });

    // On the log page the just-created assign entry is the latest change
    // for this session, so the topmost Dungeon Crawl row exposes a Revert
    // button. (Rows are ordered newest-first, so .first() is the latest.)
    await page.goto('/panel/event/sunhaven-festival/timetable/log/');
    const latestAssignRow = page
      .getByRole('row', { name: /Dungeon Crawl/ })
      .filter({ hasText: 'Assigned' })
      .first();
    await expect(latestAssignRow).toBeVisible();
    await expect(
      latestAssignRow.getByRole('button', { name: 'Revert' }),
    ).toBeVisible();

    // Now unassign the same session — this supersedes the assign entry.
    await page.goto('/panel/event/sunhaven-festival/timetable/');
    await page
      .locator('#timetable-grid')
      .getByText('Dungeon Crawl')
      .click();
    await expect(
      leftPane.getByRole('button', { name: 'Unassign' }),
    ).toBeVisible({ timeout: 5000 });
    await leftPane.getByRole('button', { name: 'Unassign' }).click();
    await expect(
      page.locator('#session-list').getByText('Dungeon Crawl'),
    ).toBeVisible({ timeout: 10000 });

    // The newer "Removed" entry is now the latest change for the session and
    // keeps its Revert button...
    await page.goto('/panel/event/sunhaven-festival/timetable/log/');
    const latestRemovedRow = page
      .getByRole('row', { name: /Dungeon Crawl/ })
      .filter({ hasText: 'Removed' })
      .first();
    await expect(latestRemovedRow).toBeVisible();
    await expect(
      latestRemovedRow.getByRole('button', { name: 'Revert' }),
    ).toBeVisible();

    // ...while every superseded "Assigned" entry for the session (now that a
    // newer "Removed" exists) must offer no Revert button at all.
    const supersededAssignRows = page
      .getByRole('row', { name: /Dungeon Crawl/ })
      .filter({ hasText: 'Assigned' });
    await expect(supersededAssignRows.first()).toBeVisible();
    await expect(
      supersededAssignRows.getByRole('button', { name: 'Revert' }),
    ).toHaveCount(0);
  });

  // --- Overview Page ---

  test('overview page loads with heatmap and track progress', async ({
    page,
  }) => {
    await page.goto(
      '/panel/event/sunhaven-festival/timetable/overview/',
    );

    await expect(
      page.getByRole('heading', {
        name: 'Organizer Overview',
      }),
    ).toBeVisible();

    // Tab navigation
    await expect(
      page.getByRole('tab', { name: 'Organizer Overview' }),
    ).toBeVisible();

    await page.screenshot({
      path: 'test-results/timetable-overview.png',
      fullPage: true,
    });
  });

  test('overview page reports hours left to fill', async ({
    page,
  }) => {
    await page.goto(
      '/panel/event/sunhaven-festival/timetable/overview/',
    );

    // Hours-to-fill section with its capacity stats.
    await expect(
      page.getByRole('heading', { name: 'Hours to fill' }),
    ).toBeVisible();
    await expect(page.getByText('Scheduled hours')).toBeVisible();
    await expect(page.getByText('Capacity hours')).toBeVisible();
    await expect(page.getByText(/\d+% filled/)).toBeVisible();

    await page.screenshot({
      path: 'test-results/timetable-overview-hours.png',
      fullPage: true,
    });
  });

  // --- Tab Navigation ---

  test('tabs navigate between timetable sub-pages', async ({
    page,
  }) => {
    await page.goto('/panel/event/sunhaven-festival/timetable/');

    // Click Activity Log tab
    await page.getByRole('tab', { name: 'Activity Log' }).click();
    await expect(page).toHaveURL(/\/timetable\/log\//);

    // Click Organizer Overview tab
    await page.getByRole('tab', { name: 'Organizer Overview' }).click();
    await expect(page).toHaveURL(/\/timetable\/overview\//);

    // Click Schedule tab to go back
    await page.getByRole('tab', { name: 'Schedule', exact: true }).click();
    await expect(page).toHaveURL(/\/timetable\/$/);
  });
});
