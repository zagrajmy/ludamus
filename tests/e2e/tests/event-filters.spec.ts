import { expect, test } from '@playwright/test';

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
  const visibleCards = '.session-card-wrapper:visible .session-card';

  test.beforeEach(async ({ page }) => {
    await page.goto('/chronology/event/autumn-open/');
    await expect(page.locator(visibleCards)).toHaveCount(3);
  });

  test('matches multiple tokens across title and host, ignoring diacritics', async ({
    page,
  }) => {
    // "Przygoda w Mieście Neonów" hosted by "Radek MG": tokens span the
    // title (sans diacritics) and the host name.
    await page.locator('#session-filter').fill('przygoda neonow radek');

    const cards = page.locator(visibleCards);
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText('Przygoda w Mieście Neonów');
  });

  test('matches a token from the title and a token from the host', async ({
    page,
  }) => {
    await page.locator('#session-filter').fill('mega alex');

    const cards = page.locator(visibleCards);
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText('Mega Strategy Lab');
  });

  test('shows the empty state when nothing matches', async ({ page }) => {
    await page.locator('#session-filter').fill('zzzznomatch');

    await expect(page.locator(visibleCards)).toHaveCount(0);
    await expect(page.locator('#filter-no-results')).toBeVisible();
  });
});
