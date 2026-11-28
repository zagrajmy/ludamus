import { type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

const SETTINGS_URL = "/panel/event/lakeside-weekend/settings/";

// Headless runners draw no WebGPU, and some do; taking it away gives every
// run the same path, the one a browser without WebGPU shows its people.
const withoutWebGpu = (page: Page) =>
  page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "gpu", { configurable: true, get: () => undefined });
  });

test.use({ storageState: managerState });

test.describe("Cover designer on the event settings", () => {
  test("is offered once, beside the cover and not the logo", async ({ page }) => {
    await page.goto(SETTINGS_URL);

    await expect(page.getByRole("button", { name: "Design a cover" })).toHaveCount(1);
    await expect(page.getByLabel("Logo", { exact: true })).toBeAttached();
    await expect(page.getByRole("dialog", { name: "Design a cover" })).toHaveCount(0);
  });

  test("opens on the same calm design and says when the browser cannot draw", async ({ page }) => {
    await withoutWebGpu(page);
    await installCspViolationCollector(page);
    await page.goto(SETTINGS_URL);
    const trigger = page.getByRole("button", { name: "Design a cover" });
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: "Design a cover" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("radio", { name: "Dice" })).toBeChecked();
    const accent = dialog.getByRole("slider", { name: "Accent" });
    await expect(accent).toBeVisible();
    await dialog.getByRole("radio", { name: "Trail map" }).check();
    await expect(accent).toBeHidden();
    await dialog.getByRole("radio", { name: "Dice" }).check();
    await expect(accent).toBeVisible();
    await expect(dialog.getByRole("radio", { name: "Hall" })).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "No text" })).toBeChecked();
    await expect(dialog.getByRole("alert")).toHaveText(
      "This browser cannot draw covers. Open the page in a recent Chrome, Edge or Safari, or upload a picture instead.",
    );
    await expect(dialog.getByRole("button", { name: "Use cover" })).toBeDisabled();

    await dialog.getByRole("radio", { name: "Add text" }).check();
    const words = dialog.getByRole("textbox", { name: "Text", exact: true });
    await expect(words).toHaveValue("");
    await words.fill("Sobota: RPG od rana");
    const cropNote = dialog.getByText("Cards crop the top and bottom");
    await dialog.getByRole("radio", { name: "Top left" }).check();
    await expect(cropNote).toBeVisible();
    await dialog.getByRole("radio", { name: "Middle right" }).check();
    await dialog.getByRole("radio", { name: "Align right" }).check();
    await expect(cropNote).toBeHidden();

    const plate = dialog.getByRole("checkbox", { name: "Background behind text" });
    await expect(plate).toBeChecked();
    await plate.uncheck();
    await expect(dialog.getByRole("radio", { name: "Auto" })).toBeChecked();
    await dialog.getByRole("radio", { name: "Light" }).check();
    const textSize = dialog.getByRole("slider", { name: "Text size" });
    await textSize.fill("1.8");
    await expect(dialog.getByText("180%")).toBeVisible();

    const facts = {
      align: await dialog.getByRole("radio", { name: "Align right" }).isChecked(),
      color: await dialog.getByRole("radio", { name: "Light" }).isChecked(),
      plate: await plate.isChecked(),
      position: await dialog.getByRole("radio", { name: "Middle right" }).isChecked(),
      size: await textSize.inputValue(),
      words: await words.inputValue(),
    };
    await attachArtifacts(test.info(), { name: "cover-designer-text", region: dialog, facts });

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel("Cover image", { exact: true })).toHaveValue("");
    await assertNoCspViolations(page);
  });
});
