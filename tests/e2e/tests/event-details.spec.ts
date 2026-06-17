import { devices, expect, test } from '@playwright/test';

test.describe('Event detail page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/chronology/event/autumn-open/');
  });

  test('shows event information and enrollment status pill', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Autumn Open Playtest' })).toBeVisible();

    // Status pills are capped at two. This event has enrollment and proposals
    // open, so those win and the lower-priority "Upcoming" pill is dropped.
    // Enrollment status is a compact pill in the hero, not a full-width banner.
    await expect(page.getByText('Enrollment Open')).toBeVisible();
    await expect(page.getByText('Proposals Open')).toBeVisible();
    await expect(page.getByText('Upcoming')).toHaveCount(0);
  });

  test('renders session cards with locations and opens detail modal', async ({ page }) => {
    const sessionCards = page.locator('.session-card');
    await expect(sessionCards).toHaveCount(3);

    const megaStrategyCard = sessionCards.filter({ hasText: 'Mega Strategy Lab' });
    await expect(megaStrategyCard).toContainText('Convention Center');
    await expect(megaStrategyCard).toContainText('Main Hall');
    await expect(megaStrategyCard).toContainText('East Wing');

    await megaStrategyCard.getByRole('link', { name: 'Open details for Mega Strategy Lab' }).click();

    const detailDialog = page.getByRole('dialog', { name: 'Mega Strategy Lab' });
    await expect(detailDialog).toBeVisible();
    await expect(detailDialog).toContainText('Alex Morgan');

    await detailDialog.getByRole('button', { name: 'Close' }).click();
    await expect(detailDialog).toBeHidden();
  });

  test(
    'mobile session modal closes on iOS tap (touchmove not cancelled)',
    async ({ browser, browserName }) => {
      test.skip(browserName === 'firefox', 'Firefox does not support mobile emulation');
      const context = await browser.newContext({
        ...devices['iPhone 14 Pro'],
        baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
      });
      const page = await context.newPage();

      await page.goto('/chronology/event/autumn-open/');
      await page
        .locator('.session-card')
        .nth(1)
        .getByRole('link')
        .click();
      await page.waitForTimeout(1000);

      const detailDialog = page.getByRole('dialog', {
        name: 'Cozy Storytellers Circle',
      });
      const closeButton = detailDialog.getByRole('button', { name: 'Close' });
      await expect(closeButton).toBeInViewport();

      const pageScrollLocked = await page.evaluate(() => {
        const bodyOverflow = getComputedStyle(document.body).overflowY;
        const bodyPosition = getComputedStyle(document.body).position;
        return bodyOverflow === 'hidden' || bodyPosition === 'fixed';
      });
      expect(pageScrollLocked).toBe(true);

      // iOS turns the start of a tap into a touchmove. The page-scroll lock
      // must not cancel touchmoves on modal controls, because that makes the
      // Close button untappable on iOS. Verify it's allowed now.
      const closeTouchMoveAllowed = await closeButton.evaluate((close) => {
        const move = new Event('touchmove', { bubbles: true, cancelable: true });
        Object.defineProperties(move, {
          targetTouches: { value: [{ clientY: 200 }] },
          touches: { value: [{ clientY: 200 }] },
        });

        close.dispatchEvent(move);
        return !move.defaultPrevented;
      });
      expect(closeTouchMoveAllowed).toBe(true);

      await closeButton.click();
      await expect(detailDialog).toBeHidden();
      await context.close();
    },
  );

  test('allows iOS touch scrolling inside long mobile session modal content', async ({ browser, browserName }) => {
    test.skip(browserName === 'firefox', 'Firefox does not support mobile emulation');
    const context = await browser.newContext({
      ...devices['iPhone 14 Pro'],
      baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    });
    await context.addInitScript(() => {
      Object.defineProperty(window.navigator, 'platform', { get: () => 'iPhone' });
      Object.defineProperty(window.navigator, 'maxTouchPoints', { get: () => 1 });
    });
    const page = await context.newPage();

    await page.goto('/chronology/event/autumn-open/');
    const sessionId = await page.locator('.session-card').nth(1).getAttribute('data-session-id');
    expect(sessionId).not.toBeNull();

    await page.evaluate((id) => {
      const description = document.querySelector(`#session-${id} [id^="info-"] div.prose`);
      if (!description) throw new Error('Missing session description');
      description.innerHTML = Array.from(
        { length: 28 },
        (_, index) => `<p>Long mobile session description paragraph ${index + 1}.</p>`,
      ).join('');
    }, sessionId);

    await page.locator('.session-card').nth(1).getByRole('link').click();
    const detailDialog = page.getByRole('dialog', {
      name: 'Cozy Storytellers Circle',
    });
    await expect(detailDialog).toBeVisible();

    const mobileModalLayout = await page.evaluate(() => {
      const dialog = document.querySelector('dialog[open]');
      const tabContent = dialog?.querySelector('.tab-content');
      if (!(dialog instanceof HTMLElement) || !(tabContent instanceof HTMLElement)) return null;

      const dialogBox = dialog.getBoundingClientRect();
      const tabContentBox = tabContent.getBoundingClientRect();
      return {
        dialogHeight: dialogBox.height,
        tabContentHeight: tabContentBox.height,
        viewportHeight: window.innerHeight,
      };
    });
    expect(mobileModalLayout).not.toBeNull();
    if (mobileModalLayout === null) {
      throw new Error('Mobile modal layout metrics were unavailable');
    }
    expect(mobileModalLayout.dialogHeight).toBeGreaterThan(
      mobileModalLayout.viewportHeight * 0.75,
    );
    expect(mobileModalLayout.tabContentHeight).toBeGreaterThan(240);

    const touchMoveAllowed = await page.evaluate(() => {
      const dialog = document.querySelector('dialog[open]');
      const activePanel = dialog?.querySelector('.tab-panel[data-active]');
      const text = activePanel?.querySelector('p');
      if (!dialog || !(activePanel instanceof HTMLElement) || !text) return false;

      const start = new Event('touchstart', { bubbles: true, cancelable: true });
      Object.defineProperties(start, {
        targetTouches: { value: [{ clientY: 300 }] },
        touches: { value: [{ clientY: 300 }] },
      });
      const move = new Event('touchmove', { bubbles: true, cancelable: true });
      Object.defineProperties(move, {
        targetTouches: { value: [{ clientY: 200 }] },
        touches: { value: [{ clientY: 200 }] },
      });

      text.dispatchEvent(start);
      text.dispatchEvent(move);

      return activePanel.scrollHeight > activePanel.clientHeight && !move.defaultPrevented;
    });
    expect(touchMoveAllowed).toBe(true);

    await detailDialog.getByRole('button', { name: 'Close' }).click();
    await expect(detailDialog).toBeHidden();
    await context.close();
  });
});

test.describe('Anonymous code modal', () => {
  test.beforeEach(async ({ page }) => {
    // Drop into anonymous-enrollment mode for an event that allows it; the
    // banner with "Enter Different Code" only renders for active anonymous
    // sessions on /chronology/event/<slug>/.
    await page.goto('/chronology/event/autumn-open/anonymous/do/activate');
    await expect(page.getByRole('heading', { name: 'Anonymous Mode Active' })).toBeVisible();
  });

  test('opens the code-entry dialog from the banner and cancels back out', async ({ page }) => {
    await page.getByRole('link', { name: /Enter Different Code/ }).click();

    const dialog = page.getByRole('dialog', { name: 'Enter Different Code' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Anonymous Code')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Switch to This Code' })).toBeVisible();

    const pageScrollLocked = await page.evaluate(() => {
      const bodyOverflow = getComputedStyle(document.body).overflowY;
      const bodyPosition = getComputedStyle(document.body).position;
      return bodyOverflow === 'hidden' || bodyPosition === 'fixed';
    });
    expect(pageScrollLocked).toBe(true);

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
  });

  test('closes the code-entry dialog from the X button', async ({ page }) => {
    await page.getByRole('link', { name: /Enter Different Code/ }).click();

    const dialog = page.getByRole('dialog', { name: 'Enter Different Code' });
    await expect(dialog).toBeVisible();

    await dialog.getByRole('button', { name: 'Close' }).click();
    await expect(dialog).toBeHidden();
  });

  test('rejects an unknown code with a flash message and stays on the event', async ({ page }) => {
    await page.getByRole('link', { name: /Enter Different Code/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Enter Different Code' });
    await dialog.getByLabel('Anonymous Code').fill('zzzz99');
    await dialog.getByRole('button', { name: 'Switch to This Code' }).click();

    await expect(page).toHaveURL(/\/chronology\/event\/autumn-open/);
    await expect(page.getByText(/Invalid code/i)).toBeVisible();
  });
});
