import { type Locator, type Page } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";

const SETTINGS_URL = "/panel/event/lakeside-weekend/settings/";
const MAX_TEXTS = 6;

// Headless runners draw no WebGPU, and some do; taking it away gives every
// run the same path, the one a browser without WebGPU shows its people.
const withoutWebGpu = (page: Page) =>
  page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "gpu", { configurable: true, get: () => undefined });
  });

const openDesigner = async (page: Page): Promise<Locator> => {
  await withoutWebGpu(page);
  await installCspViolationCollector(page);
  await page.goto(SETTINGS_URL);
  await page.getByRole("button", { name: "Design a cover" }).click();
  const dialog = page.getByRole("dialog", { name: "Design a cover" });
  await expect(dialog).toBeVisible();
  return dialog;
};

/** A point on the preview, as fractions of its width and height. */
const spot = async (preview: Locator, x: number, y: number) => {
  const box = (await preview.boundingBox())!;
  return { x: box.x + box.width * x, y: box.y + box.height * y };
};

test.use({ storageState: managerState });

test.describe("Cover designer on the event settings", () => {
  test("is offered once, beside the cover and not the logo", async ({ page }) => {
    await page.goto(SETTINGS_URL);

    await expect(page.getByRole("button", { name: "Design a cover" })).toHaveCount(1);
    await expect(page.getByLabel("Logo", { exact: true })).toBeAttached();
    await expect(page.getByRole("dialog", { name: "Design a cover" })).toHaveCount(0);
  });

  test("opens on the same calm design and says when the browser cannot draw", async ({ page }) => {
    const dialog = await openDesigner(page);

    await expect(dialog.getByRole("radio", { name: "Dice" })).toBeChecked();
    const accent = dialog.getByRole("slider", { name: "Accent" });
    await expect(accent).toBeVisible();
    await dialog.getByRole("radio", { name: "Trail map" }).check();
    await expect(accent).toBeHidden();
    await dialog.getByRole("radio", { name: "Dice" }).check();
    await expect(accent).toBeVisible();
    await expect(dialog.getByRole("radio", { name: "Hall" })).toBeChecked();
    await expect(dialog.getByRole("list", { name: "Texts" }).getByRole("listitem")).toHaveCount(0);
    await expect(dialog.getByRole("alert")).toHaveText(
      "This browser cannot draw covers. Open the page in a recent Chrome, Edge or Safari, or upload a picture instead.",
    );
    await expect(dialog.getByRole("button", { name: "Use cover" })).toBeDisabled();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel("Cover image", { exact: true })).toHaveValue("");
    await assertNoCspViolations(page);
  });

  test("puts several texts on the cover, each with its own settings", async ({ page }) => {
    const dialog = await openDesigner(page);
    const texts = dialog.getByRole("list", { name: "Texts" });
    const words = dialog.getByRole("textbox", { name: "Text", exact: true });
    const positions = dialog.getByRole("radiogroup", { name: "Position" });
    const preview = dialog.getByRole("img", { name: "Cover preview" });

    await dialog.getByRole("button", { name: "Add text" }).click();
    await expect(texts.getByRole("listitem")).toHaveCount(1);
    await expect(words).toBeFocused();
    await expect(words).toHaveValue("");
    await words.fill("Sobota: RPG od rana");
    await expect(
      texts.getByRole("button", { exact: true, name: "Sobota: RPG od rana" }),
    ).toHaveAttribute("aria-current", "true");

    const cropNote = dialog.getByText("Cards crop the top and bottom");
    await positions.getByRole("radio", { name: "Top left" }).check();
    await expect(cropNote).toBeVisible();
    await positions.getByRole("radio", { name: "Middle right" }).check();
    await expect(cropNote).toBeHidden();
    await dialog.getByRole("radio", { name: "Align left" }).focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(dialog.getByRole("radio", { name: "Align right" })).toBeChecked();
    const plate = dialog.getByRole("checkbox", { name: "Background behind text" });
    await expect(plate).toBeChecked();
    await plate.uncheck();
    await expect(dialog.getByRole("radio", { name: "Auto" })).toBeChecked();
    await dialog.getByRole("radio", { name: "Light" }).check();
    await dialog.getByRole("slider", { name: "Text size" }).fill("1.4");
    await expect(dialog.getByText("140%")).toBeVisible();

    // The Text tool: pick it, click the preview, and a second text lands there.
    await dialog.getByRole("radio", { name: "Select" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(dialog.getByRole("radio", { name: "Text", exact: true })).toBeChecked();
    await expect(dialog.getByText("Click the preview where the text should go.")).toBeVisible();
    const target = await spot(preview, 0.3, 0.3);
    await page.mouse.click(target.x, target.y);
    await expect(texts.getByRole("listitem")).toHaveCount(2);
    await expect(dialog.getByRole("radio", { name: "Select" })).toBeChecked();
    await expect(words).toBeFocused();
    await expect(words).toHaveValue("");
    await expect(positions.getByRole("radio", { checked: true })).toHaveCount(0);
    await words.fill("od 10:00");
    await expect(plate).toBeChecked();
    await expect(dialog.getByRole("radio", { name: "Auto" })).toBeChecked();

    // Each text keeps its own settings.
    await texts.getByRole("button", { exact: true, name: "Sobota: RPG od rana" }).click();
    await expect(words).toHaveValue("Sobota: RPG od rana");
    await expect(plate).not.toBeChecked();
    await expect(dialog.getByRole("radio", { name: "Light" })).toBeChecked();
    await expect(positions.getByRole("radio", { name: "Middle right" })).toBeChecked();

    // Dragging the text on the preview moves it off the grid's nine spots.
    const from = await spot(preview, 0.9, 0.5);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(from.x - 60, from.y + 10, { steps: 6 });
    await page.mouse.up();
    await expect(positions.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(
      texts.getByRole("button", { exact: true, name: "Sobota: RPG od rana" }),
    ).toHaveAttribute("aria-current", "true");

    await dialog.getByRole("button", { name: "Remove “od 10:00”" }).click();
    await expect(texts.getByRole("listitem")).toHaveCount(1);
    await expect(texts.getByRole("button", { exact: true, name: "od 10:00" })).toHaveCount(0);

    const facts = {
      texts: await texts.getByRole("listitem").allInnerTexts(),
      words: await words.inputValue(),
    };
    await attachArtifacts(test.info(), { name: "cover-designer-texts", region: dialog, facts });

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel("Cover image", { exact: true })).toHaveValue("");
    await assertNoCspViolations(page);
  });

  test("stops adding texts at six", async ({ page }) => {
    const dialog = await openDesigner(page);
    const add = dialog.getByRole("button", { name: "Add text" });

    for (let added = 0; added < MAX_TEXTS; added += 1) await add.click();

    await expect(dialog.getByRole("list", { name: "Texts" }).getByRole("listitem")).toHaveCount(
      MAX_TEXTS,
    );
    await expect(add).toBeDisabled();
    await expect(dialog.getByText("A cover holds up to 6 texts.")).toBeVisible();
  });
});
