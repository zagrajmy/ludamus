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

  test(
    'mobile session modal opened over a scrolled page keeps the Close button tappable on iOS',
    async ({ browser, browserName }) => {
      test.skip(browserName === 'firefox', 'Firefox does not support mobile emulation');
      const context = await browser.newContext({
        ...devices['iPhone 14 Pro'],
        baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
      });
      const page = await context.newPage();

      await page.goto('/chronology/event/autumn-open/');

      // Guarantee the document is scrolled before the modal opens. iOS Safari
      // ignores `overflow: hidden` on <body>, so a top-layer dialog opened over
      // a scrolled document hit-tests as if the page were at the top — taps on
      // the visually-centred Close button land on the content behind it. The
      // scroll lock must pin the body so the document offset is neutralised.
      // Open the modal with a scripted click so Playwright does not auto-scroll
      // the trigger into view (which would reset the offset we set up here). The
      // scroll position captured is exactly what the lock sees when it pins.
      const scrolledY = await page.evaluate(() => {
        const spacer = document.createElement('div');
        spacer.style.height = '1500px';
        document.body.appendChild(spacer);
        window.scrollTo(0, 1000);
        const y = window.scrollY;
        const link = document
          .querySelectorAll('.session-card')[1]
          ?.querySelector<HTMLAnchorElement>('a[aria-controls]');
        link?.click();
        return y;
      });
      expect(scrolledY).toBeGreaterThan(0);

      const detailDialog = page.getByRole('dialog', { name: 'Cozy Storytellers Circle' });
      await expect(detailDialog).toBeVisible();

      // While the modal is open the page is locked by pinning the body, so the
      // document scroll offset reads 0 and the modal's hit region lines up with
      // what's drawn. `position: fixed` is the behaviour that distinguishes the
      // fix from the old `overflow: hidden`-only lock that left iOS untappable.
      const locked = await page.evaluate(() => ({
        position: getComputedStyle(document.body).position,
        scrollY: window.scrollY,
      }));
      expect(locked.position).toBe('fixed');
      expect(locked.scrollY).toBe(0);

      // The Close button is the real hit-test target at its own centre.
      const closeButton = detailDialog.getByRole('button', { name: 'Close' });
      await expect(closeButton).toBeInViewport();
      const closeIsHitTarget = await closeButton.evaluate((close) => {
        const r = close.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return !!(hit && hit.closest('[data-modal-close]'));
      });
      expect(closeIsHitTarget).toBe(true);

      await closeButton.click();
      await expect(detailDialog).toBeHidden();

      // Closing unpins the body and restores the prior scroll position.
      const restored = await page.evaluate(() => ({
        position: getComputedStyle(document.body).position,
        scrollY: window.scrollY,
      }));
      expect(restored.position).not.toBe('fixed');
      expect(restored.scrollY).toBe(scrolledY);

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
