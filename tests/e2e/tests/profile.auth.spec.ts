import { expect, test } from '@playwright/test';

test.describe('Profile — Personal Information (edit.html)', () => {
  test('shows profile form with tab navigation', async ({ page }) => {
    await page.goto('/crowd/profile/');

    // Tab navigation
    await expect(
      page.getByRole('tab', { name: /Personal Information/ }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Connected users/ }),
    ).toBeVisible();
    await expect(page.getByRole('tab', { name: /Avatar/ })).toBeVisible();

    // Active tab is Personal Information
    const activeTab = page.getByRole('tab', { name: /Personal Information/ });
    await expect(activeTab).toHaveAttribute('aria-selected', 'true');
    await expect(activeTab).toHaveAttribute('href', /profile/);

    // Form with submit button
    await expect(
      page.getByRole('button', { name: 'OK' }),
    ).toBeVisible();

    await page.screenshot({ path: 'test-results/profile-edit.png', fullPage: true });
  });

  test('can fill and submit profile form', async ({ page }) => {
    await page.goto('/crowd/profile/');

    const nameField = page.getByLabel(/name/i);
    if (await nameField.isVisible({ timeout: 3000 }).catch(() => false)) {
      await nameField.fill(`E2E Tester ${Date.now()}`);
      await page.getByRole('button', { name: 'OK' }).click();
      // Should stay on profile or redirect back
      await expect(page).toHaveURL(/profile|crowd/);
    }
  });
});

test.describe('Profile — Connected Users (connected.html)', () => {
  test('shows connected users page with tab navigation', async ({ page }) => {
    await page.goto('/crowd/profile/connected-users/');

    // Tab navigation present
    await expect(
      page.getByRole('tab', { name: /Personal Information/ }),
    ).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Connected users/ }),
    ).toBeVisible();
    await expect(page.getByRole('tab', { name: /Avatar/ })).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Connected users/ }),
    ).toHaveAttribute('aria-selected', 'true');

    // Page content — either empty state or connected users list
    const heading = page.getByRole('heading', { level: 2 }).or(
      page.getByText(/connected/i),
    );
    await expect(heading.first()).toBeVisible();

    await page.screenshot({
      path: 'test-results/profile-connected.png',
      fullPage: true,
    });
  });
});

test.describe('Profile — Avatar (avatar.html)', () => {
  test('shows avatar selection page', async ({ page }) => {
    await page.goto('/crowd/profile/avatar/');

    // Tab navigation
    await expect(
      page.getByRole('tab', { name: /Personal Information/ }),
    ).toBeVisible();
    await expect(page.getByRole('tab', { name: /Avatar/ })).toBeVisible();
    await expect(
      page.getByRole('tab', { name: /Avatar/ }),
    ).toHaveAttribute('aria-selected', 'true');

    // Gravatar image
    await expect(page.getByAltText(/Gravatar/i)).toBeVisible();

    await page.screenshot({
      path: 'test-results/profile-avatar.png',
      fullPage: true,
    });
  });
});
