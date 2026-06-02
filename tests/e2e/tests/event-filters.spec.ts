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

  test('filters sessions by day and hour on a multi-day event', async ({ page }) => {
    await page.goto('/chronology/event/autumn-open/');

    const card = (title: string) => page.locator('.session-card', { hasText: title });
    await expect(page.locator('.session-card')).toHaveCount(3);

    await page.locator('#filter-toggle').click();
    await expect(page.locator('#filter-panel.is-open')).toBeVisible();

    // Day and hour filters only surface for multi-day events.
    await expect(page.locator('#day-filter-group')).toBeVisible();
    await expect(page.locator('#hour-filter-group')).toBeVisible();

    // Select the day holding the neon-city adventure by its value (read from the
    // card itself), so the test doesn't depend on option order or the date.
    const neonDay = await card('Przygoda w Mieście Neonów').getAttribute('data-day');
    if (!neonDay) throw new Error('neon-city card is missing data-day');
    await page.locator('#day-filter').selectOption(neonDay);
    await expect(card('Przygoda w Mieście Neonów')).toBeVisible();
    await expect(card('Mega Strategy Lab')).toBeHidden();
    await expect(card('Cozy Storytellers Circle')).toBeHidden();

    // Clearing the day and filtering by start hour narrows to the noon session.
    await page.locator('#day-filter').selectOption('');
    await page.locator('#hour-filter').selectOption('12:00');
    await expect(card('Cozy Storytellers Circle')).toBeVisible();
    await expect(card('Mega Strategy Lab')).toBeHidden();
    await expect(card('Przygoda w Mieście Neonów')).toBeHidden();
  });

  test('filters by host name case-insensitively', async ({ page }) => {
    await page.goto('/chronology/event/autumn-open/');

    const card = (title: string) => page.locator('.session-card', { hasText: title });

    // "Alex Morgan" hosts Mega Strategy Lab; a lowercase query must still match.
    await page.locator('#session-filter').fill('alex');
    await expect(card('Mega Strategy Lab')).toBeVisible();
    await expect(card('Cozy Storytellers Circle')).toBeHidden();
  });
});
