import { expect, test } from '@playwright/test';

test.describe('Anonymous proposals', () => {
  test('redirects to login when anonymous proposals are disabled', async ({
    page,
  }) => {
    await page.goto('/chronology/event/autumn-open/session/propose/');

    await expect(page).toHaveURL(/\/crowd\/login-required\/\?next=/);
  });

  test('lets an anonymous visitor submit a proposal when enabled', async ({
    page,
  }) => {
    await page.goto('/chronology/event/open-mic/session/propose/');

    const wizard = page.locator('#wizard-content');
    await expect(
      wizard.getByRole('heading', { name: 'Your Information' }),
    ).toBeVisible();
    await page.locator('#id_contact_email').fill('anon@example.com');
    await page.getByRole('button', { name: /Continue/ }).click();

    await expect(
      wizard.getByRole('heading', { name: 'Session Details' }),
    ).toBeVisible();
    await page.locator('#id_title').fill('Anonymous One-Shot');
    await page
      .locator('#id_description')
      .fill('A drop-in adventure pitched without an account.');
    await page.locator('#id_participants_limit').fill('5');
    await page.locator('#id_display_name').fill('Mystery GM');
    await page.locator('#id_duration').selectOption('PT1H');
    await page.getByRole('button', { name: /Continue/ }).click();

    await expect(
      wizard.getByRole('heading', { name: 'Review & Submit' }),
    ).toBeVisible();
    await expect(page.getByText('anon@example.com')).toBeVisible();
    await expect(page.getByText('Anonymous One-Shot')).toBeVisible();
    await page.getByRole('button', { name: 'Submit Proposal' }).click();

    await page.waitForURL(/\/open-mic\//);
    await expect(page.getByText('Anonymous One-Shot')).toBeVisible();
  });
});
