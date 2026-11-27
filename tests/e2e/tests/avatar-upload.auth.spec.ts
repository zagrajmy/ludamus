import { type Page } from "@playwright/test";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { installCspViolationCollector } from "./helpers/csp";
import { assertDropzoneBlobPreview, labeledDropzone, shownFileName } from "./helpers/dropzone";
import { expect, test } from "./helpers/fixtures";

// NOTE: Iris Lens is seeded for this spec alone (bootstrap_data.py), so a
// photo left behind by a failed run cannot reach another spec's avatars.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-avatar.json") });
test.describe.configure({ mode: "serial" });

const AVATAR_PAGE = "/crowd/profile/avatar/";

// A 1x1 opaque PNG: a real raster the server's Pillow check accepts.
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const photoInput = (page: Page) => page.getByLabel("Your photo", { exact: true });
const photoDropzone = (page: Page) => labeledDropzone(page, "Your photo");
const navbarAvatarImage = (page: Page) =>
  page.getByRole("button", { name: "Account menu" }).locator("img");
const photoShownNote = (page: Page) =>
  page.getByText("Your photo is shown now. Without it, we show the picture chosen below.");

const removeStoredPhoto = async (page: Page): Promise<void> => {
  await page.goto(AVATAR_PAGE);
  if (!(await photoShownNote(page).isVisible())) return;
  await photoDropzone(page).getByRole("button", { name: "Remove image" }).click();
  await page.getByRole("button", { name: "Save photo" }).click();
  await expect(page.getByText("Photo removed.")).toBeVisible();
};

test.beforeEach(async ({ page }) => {
  await installCspViolationCollector(page);
  await removeStoredPhoto(page);
});

test("a member uploads a photo, sees it as their avatar, then removes it", async ({
  page,
}, testInfo) => {
  await photoInput(page).setInputFiles({
    name: "portrait.png",
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });
  await expect(shownFileName(photoDropzone(page), "portrait.png")).toBeVisible();
  await assertDropzoneBlobPreview(page, photoDropzone(page));
  await page.getByRole("button", { name: "Save photo" }).click();

  await expect(page.getByText("Photo saved.")).toBeVisible();
  await expect(photoShownNote(page)).toBeVisible();
  await expect(shownFileName(photoDropzone(page), "portrait.png")).toBeVisible();
  const navbarImage = navbarAvatarImage(page);
  await expect(navbarImage).toHaveAttribute("src", /\/users\/[0-9a-f]{32}\.png$/);
  await expect(navbarImage).toHaveJSProperty("naturalWidth", 1);
  const storedSrc = await navbarImage.getAttribute("src");

  await attachArtifacts(testInfo, {
    name: "avatar-upload",
    region: page.getByRole("main"),
    facts: { navbarAvatarSrc: storedSrc, shownFileName: "portrait.png" },
  });

  await photoDropzone(page).getByRole("button", { name: "Remove image" }).click();
  await page.getByRole("button", { name: "Save photo" }).click();

  await expect(page.getByText("Photo removed.")).toBeVisible();
  await expect(photoShownNote(page)).toBeHidden();
  await expect(photoDropzone(page).getByText("Click to upload")).toBeVisible();
  await expect(navbarAvatarImage(page)).not.toHaveAttribute("src", storedSrc ?? "");
});

test("a file that is not an image is refused inside the dropzone", async ({ page }) => {
  await photoInput(page).setInputFiles({
    name: "portrait.png",
    mimeType: "image/png",
    buffer: Buffer.from("not an image"),
  });
  await page.getByRole("button", { name: "Save photo" }).click();

  await expect(page.getByText("Please correct the errors below.")).toBeVisible();
  await expect(
    photoDropzone(page).getByText(
      "Upload a valid image. The file you uploaded was either not an image or a corrupted image.",
    ),
  ).toBeVisible();
  await expect(photoInput(page)).toHaveAttribute("aria-invalid", "true");
  await expect(photoShownNote(page)).toBeHidden();
});
