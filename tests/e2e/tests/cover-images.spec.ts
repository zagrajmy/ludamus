import { expect, test, type Page } from '@playwright/test';

const PNG_BYTES = Buffer.from(
  '89504e470d0a1a0a0000000d4948445200000001000000010802000000' +
    '907753de0000000c49444154789c63606060000000040001f6173855' +
    '0000000049454e44ae426082',
  'hex',
);

const GIF_BYTES = Buffer.from(
  '47494638376101000100810000ffffff000000000000000000' +
    '2c000000000100010000080400010404003b',
  'hex',
);

const coverImageInput = (page: Page) =>
  page.getByLabel('Cover image', { exact: true });

const coverDropzone = (page: Page) =>
  coverImageInput(page).locator('xpath=ancestor::label[@data-dropzone]');

test.describe.configure({ mode: 'serial' });

test.describe('Event cover image upload', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin/login/');
    await page.getByLabel('Username:').fill('e2e-manager');
    await page.getByLabel('Password:').fill('e2e-manager-123');
    await page.getByRole('button', { name: /Log in/i }).click();
  });

  test('manager uploads cover image via the dropzone', async ({ page }) => {
    await page.goto('/panel/event/lakeside-weekend/settings/');

    const dropzone = coverDropzone(page);
    const uploadPrompt = dropzone.getByText('Click to upload');
    await expect(uploadPrompt).toBeVisible();

    await coverImageInput(page).setInputFiles({
      name: 'cover.png',
      mimeType: 'image/png',
      buffer: PNG_BYTES,
    });

    await expect(uploadPrompt).toBeHidden();
    await expect(
      dropzone.getByRole('button', { name: 'Remove image' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();

    await page.goto('/panel/event/lakeside-weekend/settings/');
    await expect(coverDropzone(page).getByText('Click to upload')).toBeHidden();
    await expect(
      coverDropzone(page).getByRole('button', { name: 'Remove image' }),
    ).toBeVisible();
  });

  test('manager removes a saved cover via the clear button', async ({
    page,
  }) => {
    await page.goto('/panel/event/lakeside-weekend/settings/');
    await coverImageInput(page).setInputFiles({
      name: 'cover.png',
      mimeType: 'image/png',
      buffer: PNG_BYTES,
    });
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();

    await page.goto('/panel/event/lakeside-weekend/settings/');
    await expect(coverDropzone(page).getByText('Click to upload')).toBeHidden();

    await coverDropzone(page)
      .getByRole('button', { name: 'Remove image' })
      .click();
    await expect(coverDropzone(page).getByText('Click to upload')).toBeVisible();
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();

    await page.goto('/panel/event/lakeside-weekend/settings/');
    await expect(coverDropzone(page).getByText('Click to upload')).toBeVisible();
  });

  test('rejects oversize file with error inside the dropzone', async ({
    page,
  }) => {
    await page.goto('/panel/event/lakeside-weekend/settings/');

    const oversize = Buffer.concat([
      PNG_BYTES,
      Buffer.alloc(8 * 1024 * 1024 + 1, 0),
    ]);
    await coverImageInput(page).setInputFiles({
      name: 'huge.png',
      mimeType: 'image/png',
      buffer: oversize,
    });

    await page.getByRole('button', { name: 'Save Settings' }).click();

    await expect(page.getByText(/Image too large/i)).toBeVisible();
  });

  test('rejects unsupported (GIF) format with error inside the dropzone', async ({
    page,
  }) => {
    await page.goto('/panel/event/lakeside-weekend/settings/');

    await expect(coverImageInput(page)).toHaveAttribute(
      'accept',
      'image/jpeg,image/png,image/webp,image/avif',
    );

    await coverImageInput(page).setInputFiles({
      name: 'cover.gif',
      mimeType: 'image/gif',
      buffer: GIF_BYTES,
    });

    await page.getByRole('button', { name: 'Save Settings' }).click();

    await expect(page.getByText(/Unsupported image format/i)).toBeVisible();
  });
});
