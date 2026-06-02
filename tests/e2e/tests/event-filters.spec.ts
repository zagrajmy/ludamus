import { expect, type Page, test } from '@playwright/test';

const MOBILE_WIDTH = 375;

test.describe('Event filter panel', () => {
  test('filter panel does not overflow viewport on mobile', async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: MOBILE_WIDTH, height: 812 },
    });
    const page = await context.newPage();

    await page.goto('/chronology/event/autumn-open/');
    await page.locator('#filter-toggle').click();
    await expect(page.locator('#filter-panel.is-open')).toBeVisible();

    const box = await page.locator('#filter-panel').boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE_WIDTH);

    await context.close();
  });
});

test.describe('Event fuzzy search', () => {
  // Each session card exposes an accessible link "Open details for <title>",
  // so we can assert on cards by role + name rather than CSS classes.
  const card = (page: Page, title: string) =>
    page.getByRole('link', { name: `Open details for ${title}` });

  const searchBox = (page: Page) =>
    page.getByRole('textbox', { name: 'Filter by title or host...' });

  const MEGA = 'Mega Strategy Lab';
  const COZY = 'Cozy Storytellers Circle';
  const NEON = 'Przygoda w Mieście Neonów';

  test.beforeEach(async ({ page }) => {
    await page.goto('/chronology/event/autumn-open/');
    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeVisible();
  });

  test('matches multiple tokens across title and host, ignoring diacritics', async ({
    page,
  }) => {
    // "Przygoda w Mieście Neonów" hosted by "Radek Włodarczyk": tokens span the
    // title (sans diacritics) and the host name.
    await searchBox(page).fill('przygoda neonow radek');

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
    await expect(card(page, COZY)).toBeHidden();
  });

  test('folds the Polish "ł", which NFD leaves intact', async ({ page }) => {
    // Host "Radek Włodarczyk": "ł" has no NFD decomposition, so the
    // stroke-less query "wlodarczyk" only matches with the explicit fold.
    await searchBox(page).fill('wlodarczyk');

    await expect(card(page, NEON)).toBeVisible();
    await expect(card(page, MEGA)).toBeHidden();
  });

  test('matches a token from the title and a token from the host', async ({
    page,
  }) => {
    await searchBox(page).fill('mega alex');

    await expect(card(page, MEGA)).toBeVisible();
    await expect(card(page, NEON)).toBeHidden();
  });

  test('shows the empty state when nothing matches', async ({ page }) => {
    await searchBox(page).fill('zzzznomatch');

    await expect(card(page, MEGA)).toBeHidden();
    await expect(page.getByText('No sessions match your filters')).toBeVisible();
  });
});
