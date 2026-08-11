import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// A 1x1 opaque PNG — the mark only has to be a real raster the browser will
// decode, so the smallest valid one keeps the fixture inline.
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const GUILD = "Topory";
const PRESENTER_EMAIL = "e2e@test.local";

const logoInput = (page: Page) => page.getByLabel("Logo", { exact: true });

const signInAsManager = async (page: Page): Promise<void> => {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
};

const deleteGuildIfPresent = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/");
  const row = page.getByRole("row").filter({ hasText: GUILD });
  if ((await row.count()) === 0) return;
  await row.getByRole("link", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete guild" }).click();
  await expect(page.getByText("Guild deleted.")).toBeVisible();
};

test.describe.configure({ mode: "serial" });

test.describe("Guilds", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await deleteGuildIfPresent(page);
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await signInAsManager(page);
    await deleteGuildIfPresent(page);
    await page.close();
  });

  test("the empty state explains what a guild is and offers the way in", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/");

    await expect(page.getByText("No guilds yet.")).toBeVisible();
    await expect(
      page.getByText(
        "A guild's mark shows beside its members' names on every programme card they present.",
      ),
    ).toBeVisible();
    await page.getByRole("link", { name: "New guild" }).first().click();

    await expect(page.getByLabel("Guild name")).toBeVisible();
  });

  test("a manager creates a guild with a mark and sees it in the list", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/create/");

    await page.getByLabel("Guild name").fill(GUILD);
    await logoInput(page).setInputFiles({
      name: "mark.png",
      mimeType: "image/png",
      buffer: PNG_BYTES,
    });
    await page.getByRole("button", { name: "Create guild" }).click();

    await expect(page.getByText("Guild created.")).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: GUILD });
    await expect(row).toBeVisible();
    // The mark is an <img> inside the row, so it is the row's own picture
    // rather than the page-level sphere logo.
    await expect(row.locator("img")).toHaveJSProperty("naturalWidth", 1);
  });

  test("a manager adds a presenter and can take them out again", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/create/");
    await page.getByLabel("Guild name").fill(GUILD);
    await page.getByRole("button", { name: "Create guild" }).click();
    await page
      .getByRole("row")
      .filter({ hasText: GUILD })
      .getByRole("link", {
        name: "Edit",
      })
      .click();

    await expect(page.getByText("Nobody in this guild yet.")).toBeVisible();
    await page.getByLabel("Email or Discord username").fill(PRESENTER_EMAIL);
    await page.getByRole("button", { name: "Add presenter" }).click();

    await expect(page.getByText("Presenter added.")).toBeVisible();
    const roster = page.getByRole("listitem").filter({ hasText: PRESENTER_EMAIL });
    await expect(roster).toBeVisible();

    await roster.getByRole("button", { name: /Remove .* from this guild/ }).click();

    await expect(page.getByText("Presenter removed.")).toBeVisible();
    await expect(page.getByText("Nobody in this guild yet.")).toBeVisible();
  });

  test("an unknown handle is refused instead of silently doing nothing", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/create/");
    await page.getByLabel("Guild name").fill(GUILD);
    await page.getByRole("button", { name: "Create guild" }).click();
    await page
      .getByRole("row")
      .filter({ hasText: GUILD })
      .getByRole("link", {
        name: "Edit",
      })
      .click();

    await page.getByLabel("Email or Discord username").fill("nobody@example.com");
    await page.getByRole("button", { name: "Add presenter" }).click();

    await expect(
      page.getByText("No account matches that email or Discord username."),
    ).toBeVisible();
    await expect(page.getByText("Nobody in this guild yet.")).toBeVisible();
  });

  test("a mark carrying a script is refused", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/create/");

    await page.getByLabel("Guild name").fill(GUILD);
    await logoInput(page).setInputFiles({
      name: "evil.svg",
      mimeType: "image/svg+xml",
      buffer: Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
      ),
    });
    await page.getByRole("button", { name: "Create guild" }).click();

    await expect(page.getByText(/Invalid or unsafe SVG file/i)).toBeVisible();
    await expect(page.getByLabel("Guild name")).toHaveValue(GUILD);
  });

  // Guilds is reached from the sidebar, not by typing the URL every other test
  // uses. Without this, deleting the sidebar entry breaks nothing in CI.
  test("a manager reaches guilds from the sidebar of another sphere page", async ({ page }) => {
    await page.goto("/multiverse/panel/");

    // The page's own <nav> is the site navbar; the sidebar lives in the aside.
    const sidebar = page.getByRole("complementary");
    await sidebar.getByRole("link", { name: "Guilds", exact: true }).click();

    await expect(page).toHaveURL(/\/multiverse\/panel\/guilds\/$/);
    await expect(page.getByRole("heading", { name: "Guilds", level: 2 })).toBeVisible();
    // Sphere settings owns the highlight on the page we came from; arriving at
    // Guilds has to move it, which is the whole point of the nav entry.
    await expect(sidebar.getByRole("link", { name: "Guilds", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(
      sidebar.getByRole("link", { name: "Sphere settings", exact: true }),
    ).not.toHaveAttribute("aria-current", "page");
  });
});
