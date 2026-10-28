import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

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
      facts: { source: await page.url() },
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
  });
});
