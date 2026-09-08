import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";

// The export is its own panel section, reached from the sidebar like the
// Google Docs import — not from a row action on the integrations list. These
// assert the rendered chrome; what the view puts in the context is asserted in
// tests/integration.
const EVENT = "frostfire-con";
const TIMETABLE_URL = `/panel/event/${EVENT}/timetable/`;
const INTEGRATION = "Konwencik agenda";

test.describe("Konwencik export", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("a manager reaches the export from the sidebar", async ({ page }) => {
    await page.goto(TIMETABLE_URL);

    // The site navbar is a <nav> too, so the sidebar is picked by its label.
    const sidebar = page.getByRole("navigation", { name: "Panel sections" });
    const link = sidebar.getByRole("link", { name: "Konwencik export", exact: true });

    await link.click();

    await expect(page).toHaveURL(new RegExp(`/panel/event/${EVENT}/export/$`));
    await expect(page.getByRole("heading", { name: "Konwencik export" })).toBeVisible();
    await expect(page.getByText(INTEGRATION)).toBeVisible();
    await expect(link).toHaveAttribute("aria-current", "page");
  });

  test("the export page offers its own run and save controls", async ({ page }) => {
    await page.goto(`/panel/event/${EVENT}/export/`);

    await expect(page.getByRole("button", { name: "Export now" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeVisible();
  });

  test("unused programme combinations have no preview", async ({ page }) => {
    await page.goto(`/panel/event/${EVENT}/export/`);

    await expect(page.getByRole("heading", { name: "Export preview" })).toHaveCount(0);
    await expect(page.locator("[data-konwencik-cell]")).toHaveCount(0);
  });

  test("programme samples render icons and update without saving", async ({ page }) => {
    await page.goto("/panel/event/konwencik-preview/export/");
    const samples = page.getByRole("list", { name: "Adventure", exact: true });
    await expect(samples.getByRole("listitem")).toHaveCount(1);
    await expect(samples.getByText("Unused track")).toHaveCount(0);
    await expect(samples.getByText("Workshops")).toHaveCount(0);
    await expect(page.getByText("No track", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Export preview" })).toHaveCount(0);
    await expect(page.getByText("Leave empty for no background.")).toHaveCount(0);

    const sample = samples.getByRole("listitem").filter({ hasText: "RPG" });
    const glyph = sample.locator("[data-konwencik-cell-icon]");
    await expect(page.getByLabel("Background", { exact: true }).first()).toHaveAttribute(
      "type",
      "text",
    );
    expect(
      await page
        .locator("#konwencik-settings-form")
        .evaluate((form: HTMLFormElement) => new FormData(form).get("colors-1-color")),
    ).toBe("");
    const inputGlyph = page.locator("[data-icon-field-glyph]").first();
    await expect(inputGlyph).toHaveClass(/fa-dice-d20/);
    await expect(glyph).toHaveCSS("font-family", '"Font Awesome 6 Free"');
    await expect
      .poll(() => glyph.evaluate((element) => getComputedStyle(element, "::before").content))
      .toBe('"\uf6cf"');
    await page.getByLabel("Icon", { exact: true }).first().fill("fa.gamepad");
    await expect(inputGlyph).toHaveClass(/fa-gamepad/);
    await expect
      .poll(() => glyph.evaluate((element) => getComputedStyle(element, "::before").content))
      .toBe('"\uf11b"');
    await page.getByLabel("Background", { exact: true }).first().fill("#ffffff");
    await expect(sample.locator("[data-konwencik-cell]")).toHaveCSS(
      "background-color",
      "rgb(255, 255, 255)",
    );
    await expect(glyph).toHaveCSS("color", "rgb(255, 255, 255)");
    const hex = page.getByLabel("Background", { exact: true }).first();
    const picker = page.getByLabel("Background — Color picker").first();
    await expect(picker).toHaveValue("#ffffff");
    await picker.fill("#1e88e5");
    await expect(hex).toHaveValue("#1e88e5");
    await hex.fill("#12");
    await expect(sample).toBeHidden();
    await hex.fill("");
    await expect(sample).toBeHidden();
    await hex.fill("#1e88e5");
    await expect(sample).toBeVisible();
    await page.getByLabel("Icon", { exact: true }).first().fill("fa.not-an-icon");
    await expect(sample.getByText("Preview unavailable for this icon")).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "Preview unavailable for this icon" }),
    ).toBeVisible();
    await page.getByLabel("Icon", { exact: true }).first().fill("fa.github");
    await expect(glyph).toHaveCSS("font-family", '"Font Awesome 6 Brands"');
    await expect
      .poll(() => glyph.evaluate((element) => getComputedStyle(element, "::before").content))
      .toBe('"\uf09b"');
    await page.getByLabel("Icon", { exact: true }).first().fill("");
    await expect(sample.getByText("No icon", { exact: true })).toBeVisible();
    await hex.focus();
    await hex.press("Tab");
    await expect(picker).toBeFocused();
    await picker.press("Shift+Tab");
    await expect(hex).toBeFocused();
    await hex.fill("#12");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Use a hex colour, e.g. #1e88e5.")).toBeVisible();
    await expect(hex).toHaveValue("#12");
  });

  test("hex fields remain editable without JavaScript", async ({ page, browser }) => {
    const context = await browser.newContext({
      javaScriptEnabled: false,
      locale: "en-US",
      storageState: await page.context().storageState(),
    });
    const plainPage = await context.newPage();
    await plainPage.goto(new URL("/panel/event/konwencik-preview/export/", page.url()).href);
    const hex = plainPage
      .getByRole("group", { name: "Adventure", exact: true })
      .getByLabel("Background", { exact: true });
    await expect(hex).toHaveValue("#1e88e5");
    await hex.fill("");
    await expect(hex).toHaveValue("");
    await expect(plainPage.getByLabel("Background — Color picker").first()).toBeHidden();
    await context.close();
  });

  for (const path of [TIMETABLE_URL, `/panel/event/${EVENT}/settings/`, "/design/"]) {
    test(`${path} does not load Font Awesome`, async ({ page }) => {
      const iconAssets: string[] = [];
      page.on("request", (request) => {
        if (
          /fontawesome|fa-(solid|regular|brands|v4compatibility)|konwencik-preview/i.test(
            request.url(),
          )
        )
          iconAssets.push(request.url());
      });
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      expect(iconAssets).toEqual([]);
    });
  }

  for (const width of [390, 768, 1440]) {
    test(`preview fits and stays accessible at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/panel/event/konwencik-preview/export/");
      await expect(page.getByRole("list", { name: "Adventure", exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      );
      await analyzePageAccessibility(page, { include: "main" });
    });
  }
});
