import type { Locator } from "@playwright/test";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const paintedLayer = (field: Locator): Locator => field.locator("xpath=following-sibling::pre[1]");

test.describe("Markdown descriptions", () => {
  test("formats with shortcuts, continues lists, and publishes rendered", async ({ page }) => {
    await page.goto("/encounters/create/");

    await page.getByLabel("Title").fill("Markdown night");
    await page.getByLabel("Start time").fill("2031-05-01T19:00");
    const description = page.getByLabel("Description");
    await description.click();
    await page.keyboard.type("Bring dice");
    await page.keyboard.down("Shift");
    for (const _ of "dice") await page.keyboard.press("ArrowLeft");
    await page.keyboard.up("Shift");
    await page.keyboard.press("ControlOrMeta+b");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.type(".\n\n- d20");
    await page.keyboard.press("Enter");
    await page.keyboard.type("pencil");
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
    await page.keyboard.type("See you!");

    await expect(description).toHaveValue("Bring **dice**.\n\n- d20\n- pencil\n\nSee you!");
    const painted = page.locator("pre", { hasText: "Bring **dice**." });
    await expect(painted.locator(".mdhl-strong")).toHaveText("**dice**");

    await page.getByRole("button", { name: "Create Encounter" }).click();

    await expect(page.getByRole("heading", { name: "Markdown night" })).toBeVisible();
    const body = page.locator(".prose").filter({ hasText: "Bring" });
    await expect(body.locator("strong")).toHaveText("dice");
    await expect(body.getByRole("listitem")).toHaveText(["d20", "pencil"]);
    await attachArtifacts(test.info(), {
      name: "markdown-published",
      region: body,
      facts: { source: page.url() },
    });
  });

  test("an empty list item ends the list with a blank line", async ({ page }) => {
    await page.goto("/encounters/create/");

    const description = page.getByLabel("Description");
    await description.click();
    await page.keyboard.type("1. one");
    await page.keyboard.press("Enter");
    await expect(description).toHaveValue("1. one\n2. ");
    await page.keyboard.press("Enter");
    await page.keyboard.type("after");

    await expect(description).toHaveValue("1. one\n\nafter");

    await page.keyboard.type("\n\n- item");
    for (const _ of "item") await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Enter");

    await expect(description).toHaveValue("1. one\n\nafter\n\n- \n- item");
  });

  test("without scripts the description is a plain textarea", async ({ browser }) => {
    // NOTE: a context of its own; the page fixture records script coverage,
    // which needs scripts.
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto("/encounters/create/");

    const description = page.getByLabel("Description");
    await description.fill("Plain **text**");

    await expect(description).toHaveValue("Plain **text**");
    await expect(description).not.toHaveCSS("-webkit-text-fill-color", "rgba(0, 0, 0, 0)");
    await expect(paintedLayer(description)).toBeHidden();
    await context.close();
  });

  test("a step that comes back with errors keeps the painting over its field", async ({ page }) => {
    await page.goto("/event/mothership-nights-2/session/propose/");
    const form = page.locator("#propose-details-form");
    await form.evaluate((el: HTMLFormElement) => {
      el.noValidate = true;
    });
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    const description = form.getByLabel("About this session");
    await description.fill("Still **painted**");
    const layer = paintedLayer(description);
    await expect(layer.locator(".mdhl-strong")).toHaveText("**painted**");
    await expect
      .poll(async () => {
        const [painted, typed] = await Promise.all([
          layer.boundingBox(),
          description.boundingBox(),
        ]);
        if (!painted || !typed) return null;
        return {
          x: painted.x - typed.x,
          y: painted.y - typed.y,
          width: painted.width - typed.width,
          height: painted.height - typed.height,
        };
      })
      .toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });

  test("replays mask the painted copy unless the text is published", async ({ page }) => {
    await page.goto("/encounters/create/");
    const published = paintedLayer(page.getByLabel("Description"));
    await expect(published).toBeAttached();
    await expect(published).not.toHaveAttribute("data-ph-mask");

    await page.goto("/board/create/");
    const personal = paintedLayer(page.getByLabel("Description"));
    await expect(personal).toHaveAttribute("data-ph-mask", "");
  });
});
