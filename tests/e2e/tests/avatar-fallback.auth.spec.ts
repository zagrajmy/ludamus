import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// The seeded e2e user's avatar_url points at an external host
// (bootstrap_data.py), so routing it is what makes both outcomes deterministic
// — and independent of whether the sandbox can reach that host at all.
const AVATAR_REQUEST = /pravatar\.cc/;

const PNG_BYTES = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010802000000" +
    "907753de0000000c49444154789c63606060000000040001f6173855" +
    "0000000049454e44ae426082",
  "hex",
);

const navbarAvatarImage = (page: Page) => page.locator("img[data-avatar-image]").first();

test.describe("Avatar image fallback", () => {
  test("shows the photo when it loads", async ({ page }) => {
    await page.route(AVATAR_REQUEST, (route) =>
      route.fulfill({ body: PNG_BYTES, contentType: "image/png" }),
    );

    await page.goto("/");

    await expect(navbarAvatarImage(page)).toBeVisible();
  });

  test("uncovers the initials placeholder when the photo fails", async ({ page }) => {
    await page.route(AVATAR_REQUEST, (route) => route.abort());

    await page.goto("/");

    await expect(navbarAvatarImage(page)).toBeHidden();
    await expect(page.getByRole("img", { name: "E2E Tester" }).first()).toBeVisible();
  });
});
