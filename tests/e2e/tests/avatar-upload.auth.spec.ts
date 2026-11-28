import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

// NOTE: Iris Lens is seeded for this spec alone (bootstrap_data.py), so a
// photo left behind by a failed run cannot reach another spec's avatars. She
// signs in without a social login picture, so her cards are photo and Gravatar.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-avatar.json") });
test.describe.configure({ mode: "serial" });

const AVATAR_PAGE = "/crowd/profile/avatar/";

// A 1x1 opaque PNG: a real raster the server's Pillow check accepts.
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const photoInput = (page: Page) => page.getByLabel("Upload a photo", { exact: true });
const sourceRadio = (page: Page, name: string) => page.getByRole("radio", { name, exact: true });
// The radio is visually hidden; a person clicks the card, whose title is the
// radio's label. The pick submits from a module script, so the click waits
// for the page's scripts and then for the save it sends.
const pickSource = async (page: Page, name: string): Promise<void> => {
  await page.waitForLoadState("domcontentloaded");
  const saved = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().endsWith(AVATAR_PAGE),
  );
  await page.getByText(name, { exact: true }).click();
  await saved;
};
const navbarAvatarImage = (page: Page) =>
  page.getByRole("button", { name: "Account menu" }).locator("img");
const removePhotoButton = (page: Page) => page.getByRole("button", { name: "Remove photo" });

test.beforeEach(async ({ page }) => {
  await installCspViolationCollector(page);
  await page.goto(AVATAR_PAGE);
  if (await removePhotoButton(page).isVisible()) {
    await removePhotoButton(page).click();
    await expect(page.getByText("Photo removed.")).toBeVisible();
  }
  // A picked file submits from a module script; it must be running first.
  await page.waitForLoadState("domcontentloaded");
});

test("a member uploads a photo, switches between cards, then removes it", async ({
  page,
}, testInfo) => {
  await expect(sourceRadio(page, "Your photo")).toBeDisabled();
  await expect(sourceRadio(page, "Gravatar")).toBeChecked();

  // Picking a file sends it at once: no Save button stands between the drop
  // and the new avatar.
  await photoInput(page).setInputFiles({
    name: "portrait.png",
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });

  await expect(page.getByText("Photo saved.")).toBeVisible();
  await expect(sourceRadio(page, "Your photo")).toBeChecked();
  await expect(navbarAvatarImage(page)).toHaveAttribute("src", /\/users\/[0-9a-f]{32}\.png$/);
  await expect(navbarAvatarImage(page)).toHaveJSProperty("naturalWidth", 1);
  const photoSrc = await navbarAvatarImage(page).getAttribute("src");
  await attachArtifacts(testInfo, {
    name: "avatar-upload",
    region: page.getByRole("main"),
    facts: { navbarAvatarSrc: photoSrc, checked: "Your photo" },
  });

  await pickSource(page, "Gravatar");

  await expect(page.getByText("Avatar updated.")).toBeVisible();
  await expect(sourceRadio(page, "Gravatar")).toBeChecked();
  await expect(navbarAvatarImage(page)).toHaveAttribute("src", /gravatar\.com\/avatar\//);

  await pickSource(page, "Your photo");

  await expect(page.getByText("Avatar updated.")).toBeVisible();
  await expect(sourceRadio(page, "Your photo")).toBeChecked();
  await expect(navbarAvatarImage(page)).toHaveAttribute("src", photoSrc ?? "");

  await removePhotoButton(page).click();

  await expect(page.getByText("Photo removed.")).toBeVisible();
  await expect(sourceRadio(page, "Your photo")).toBeDisabled();
  await expect(sourceRadio(page, "Gravatar")).toBeChecked();
  await assertNoCspViolations(page);
});

test("a file that is not an image is refused in the photo card", async ({ page }) => {
  await photoInput(page).setInputFiles({
    name: "portrait.png",
    mimeType: "image/png",
    buffer: Buffer.from("not an image"),
  });

  await expect(page.getByText("Please correct the errors below.")).toBeVisible();
  await expect(
    page.getByText(
      "Upload a valid image. The file you uploaded was either not an image or a corrupted image.",
    ),
  ).toBeVisible();
  await expect(photoInput(page)).toHaveAttribute("aria-invalid", "true");
  await expect(sourceRadio(page, "Your photo")).toBeDisabled();
});
