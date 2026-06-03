import { expect, test } from '@playwright/test';

// Tiny 1x1 PNG, identical to PNG_BYTES used in integration tests.
const PNG_BYTES = Buffer.from(
  '89504e470d0a1a0a0000000d4948445200000001000000010802000000' +
    '907753de0000000c49444154789c63606060000000040001f6173855' +
    '0000000049454e44ae426082',
  'hex',
);

// Tiny 1x1 GIF — used to assert that GIF uploads are rejected.
const GIF_BYTES = Buffer.from(
  '47494638376101000100810000ffffff000000000000000000' +
    '2c000000000100010000080400010404003b',
  'hex',
);

test.describe('Event cover image upload', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin/login/');
    await page.getByLabel('Username:').fill('e2e-manager');
    await page.getByLabel('Password:').fill('e2e-manager-123');
    await page.getByRole('button', { name: /Log in/i }).click();
  });

  test('manager uploads cover image via the dropzone', async ({ page }) => {
    await page.goto('/panel/event/autumn-open/settings/');

    const dropzone = page.locator('[data-dropzone]');
    const empty = dropzone.locator('[data-dropzone-empty]');
    const selected = dropzone.locator('[data-dropzone-selected]');

    // No cover yet — empty state visible, selected state hidden.
    await expect(empty).toBeVisible();
    await expect(selected).toBeHidden();

    await dropzone.locator('[data-dropzone-input]').setInputFiles({
      name: 'cover.png',
      mimeType: 'image/png',
      buffer: PNG_BYTES,
    });

    // Client-side preview kicks in: empty hides, selected shows with blob URL.
    await expect(empty).toBeHidden();
    await expect(selected).toBeVisible();
    await expect(dropzone.locator('[data-dropzone-preview]')).toHaveAttribute(
      'src',
      /^blob:/,
    );
    await expect(dropzone.locator('[data-dropzone-name]')).toHaveText(
      'cover.png',
    );

    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expect(
      page.getByText('Event settings saved successfully.'),
    ).toBeVisible();

    // Saved cover persists — dropzone hydrates with /media/ src on reload.
    await page.goto('/panel/event/autumn-open/settings/');
    await expect(page.locator('[data-dropzone-preview]')).toHaveAttribute(
      'src',
      /\/media\/events\//,
    );
  });

  test('rejects oversize file with error inside the dropzone', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/settings/');

    const oversize = Buffer.concat([
      PNG_BYTES,
      Buffer.alloc(2 * 1024 * 1024 + 1, 0),
    ]);
    await page.locator('[data-dropzone-input]').setInputFiles({
      name: 'huge.png',
      mimeType: 'image/png',
      buffer: oversize,
    });

    await page.getByRole('button', { name: 'Save Settings' }).click();

    const dropzone = page.locator('[data-dropzone]');
    await expect(dropzone).toHaveClass(/border-danger/);
    await expect(dropzone.locator('[data-dropzone-error]')).toHaveText(
      /Image too large/i,
    );
  });

  test('rejects unsupported (GIF) format with error inside the dropzone', async ({
    page,
  }) => {
    await page.goto('/panel/event/autumn-open/settings/');

    // accept attribute restricts the file picker to allowed MIME types.
    await expect(page.locator('[data-dropzone-input]')).toHaveAttribute(
      'accept',
      'image/jpeg,image/png,image/webp,image/avif',
    );

    await page.locator('[data-dropzone-input]').setInputFiles({
      name: 'cover.gif',
      mimeType: 'image/gif',
      buffer: GIF_BYTES,
    });

    await page.getByRole('button', { name: 'Save Settings' }).click();

    const dropzone = page.locator('[data-dropzone]');
    await expect(dropzone).toHaveClass(/border-danger/);
    await expect(dropzone.locator('[data-dropzone-error]')).toHaveText(
      /Unsupported image format/i,
    );
  });
});
