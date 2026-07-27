import { expect, test, type Page } from "@playwright/test";

const SVG_BYTES = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="60" height="20" viewBox="0 0 60 20">' +
    '<rect width="60" height="20" fill="#123"/></svg>',
);

const logoInput = (page: Page) => page.getByLabel("Logo", { exact: true });

const logoDropzone = (page: Page) =>
  logoInput(page).locator("xpath=ancestor::label[@data-dropzone]");

const shownFileName = (page: Page) =>
  logoDropzone(page).locator("[data-dropzone-name]").filter({ visible: true });

const removeSavedLogo = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/");
  const clear = logoDropzone(page).getByRole("button", { name: "Remove image" });
  if (!(await clear.isVisible())) return;
  await clear.click();
  await page.getByRole("button", { name: "Save Settings" }).click();
  await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();
};

test.describe.configure({ mode: "serial" });

test.describe("Sphere logo upload", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/");
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await removeSavedLogo(page);
  });

  test("manager uploads an SVG logo and sees it previewed", async ({ page }) => {
    await page.goto("/multiverse/panel/");

    const dropzone = logoDropzone(page);
    await expect(dropzone.getByText("Click to upload")).toBeVisible();

    await logoInput(page).setInputFiles({
      name: "brand.svg",
      mimeType: "image/svg+xml",
      buffer: SVG_BYTES,
    });

    await expect(dropzone.getByText("Click to upload")).toBeHidden();
    await expect(shownFileName(page)).toHaveText("brand.svg");

    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();

    await page.goto("/multiverse/panel/");
    const preview = logoDropzone(page).locator("[data-dropzone-preview]");
    await expect(preview).toHaveAttribute("src", /\.svg$/);
    await expect(preview).toHaveJSProperty("naturalWidth", 60);
  });

  test("rejects an SVG carrying a script", async ({ page }) => {
    await page.goto("/multiverse/panel/");

    await logoInput(page).setInputFiles({
      name: "evil.svg",
      mimeType: "image/svg+xml",
      buffer: Buffer.from(
        SVG_BYTES.toString().replace("</svg>", "<script>alert(1)</script></svg>"),
      ),
    });
    await page.getByRole("button", { name: "Save Settings" }).click();

    await expect(page.getByText(/Invalid or unsafe SVG file/i)).toBeVisible();
  });

  test("manager removes a saved logo via the clear button", async ({ page }) => {
    await page.goto("/multiverse/panel/");
    await logoInput(page).setInputFiles({
      name: "brand.svg",
      mimeType: "image/svg+xml",
      buffer: SVG_BYTES,
    });
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();

    await page.goto("/multiverse/panel/");
    await logoDropzone(page).getByRole("button", { name: "Remove image" }).click();
    await expect(logoDropzone(page).getByText("Click to upload")).toBeVisible();
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();

    await page.goto("/multiverse/panel/");
    await expect(logoDropzone(page).getByText("Click to upload")).toBeVisible();
  });
});
