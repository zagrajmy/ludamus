import { expect, test } from '@playwright/test';

// The delete + restore actions mutate the shared seeded "Pending Neon
// Proposal" (bootstrap_data.py), so the two scenarios run serially: delete
// first, then restore, leaving the seed state clean for other specs.
test.describe.configure({ mode: 'serial' });

const PROPOSAL_TITLE = 'Pending Neon Proposal';
const PROPOSALS_URL = '/panel/event/autumn-open/proposals/';

test.describe('Proposal delete and restore', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate as the sphere manager via Django admin, mirroring the
    // panel + timetable specs.
    await page.goto('/admin/login/', { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Username:').fill('e2e-manager');
    await page.getByLabel('Password:').fill('e2e-manager-123');
    await page.getByRole('button', { name: /Log in/i }).click();

    // Auto-accept the confirm() dialog guarding the delete/restore forms.
    page.on('dialog', (dialog) => dialog.accept());
  });

  test('soft-deletes a pending session from its detail page', async ({
    page,
  }) => {
    // The seeded pending proposal starts in the active list, with no
    // "Recently deleted" section yet.
    await page.goto(PROPOSALS_URL);
    const activeLink = page.getByRole('link', { name: PROPOSAL_TITLE });
    await expect(activeLink).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Recently deleted' }),
    ).toHaveCount(0);

    // Open the proposal detail page from the list and delete it there.
    await activeLink.click();
    await page.getByRole('button', { name: 'Delete' }).click();

    // Deleting redirects back to the proposals list: the session is gone from
    // the active table and appears under "Recently deleted" with a Restore
    // button.
    await page.waitForURL(/\/proposals\/$/);
    await expect(
      page.getByRole('link', { name: PROPOSAL_TITLE }),
    ).toHaveCount(0);

    await expect(
      page.getByRole('heading', { name: 'Recently deleted' }),
    ).toBeVisible();
    const deletedRow = page
      .getByRole('row')
      .filter({ hasText: PROPOSAL_TITLE });
    await expect(deletedRow).toBeVisible();
    await expect(
      deletedRow.getByRole('button', { name: 'Restore' }),
    ).toBeVisible();
  });

  test('restores the session from "Recently deleted"', async ({ page }) => {
    await page.goto(PROPOSALS_URL);

    // Restore from the "Recently deleted" section.
    const deletedRow = page
      .getByRole('row')
      .filter({ hasText: PROPOSAL_TITLE });
    await expect(deletedRow).toBeVisible();
    await deletedRow.getByRole('button', { name: 'Restore' }).click();

    // The session returns to the active list...
    await page.waitForURL(/\/proposals\/$/);
    await expect(
      page.getByRole('link', { name: PROPOSAL_TITLE }),
    ).toBeVisible();

    // ...and no longer shows under "Recently deleted". With nothing left to
    // restore, the whole section disappears.
    await expect(
      page.getByRole('heading', { name: 'Recently deleted' }),
    ).toHaveCount(0);
  });
});
