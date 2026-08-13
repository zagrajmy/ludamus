import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// The guild column on the panel's facilitator list, and the way into a guild it
// offers. Runs against the frostfire-con panel-lab event, where
// bootstrap_facilitators.py seeds Dana Reyes with an account of her own and Bob
// Chen without one — the two states the column has to tell apart.

// A 1x1 opaque PNG, so the mark is a real raster the browser will decode.
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

// Its own guild, not the one guilds.spec.ts creates and deletes: the two specs
// share a sphere and can run at the same time.
const GUILD = "Kuźnia";
const LINKED = "Dana Reyes";
const UNLINKED = "Bob Chen";
const FACILITATORS_URL = "/panel/event/frostfire-con/facilitators/";
const UNLINKED_EDIT_URL = "/panel/event/frostfire-con/facilitators/bob-chen/edit/";

const signInAsManager = async (page: Page): Promise<void> => {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
};

const guildRow = (page: Page) => page.getByRole("row").filter({ hasText: GUILD });

// Deleting the guild takes its memberships with it, so this resets the mark on
// the facilitator too.
const deleteGuildIfPresent = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/");
  if ((await guildRow(page).count()) === 0) return;
  await guildRow(page).getByRole("link", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete guild" }).click();
  // The row itself, not the "Guild deleted." toast: transient flashes clear
  // themselves after five seconds, which a slow page load can outlast.
  await expect(guildRow(page)).toHaveCount(0);
};

const createGuild = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/create/");
  await page.getByLabel("Guild name").fill(GUILD);
  await page.getByLabel("Logo", { exact: true }).setInputFiles({
    name: "mark.png",
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });
  await page.getByRole("button", { name: "Create guild" }).click();
  await expect(guildRow(page)).toBeVisible();
};

const facilitatorRow = (page: Page, name: string) =>
  page.getByRole("row").filter({ hasText: name });

const attachButton = (page: Page, name: string) =>
  facilitatorRow(page, name).getByRole("button", { name: `Attach ${name} to a guild` });

test.describe.configure({ mode: "serial" });

test.describe("Facilitator guild marks", () => {
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

  test("a facilitator with no account can be attached to a guild", async ({ page }) => {
    await createGuild(page);
    await page.goto(FACILITATORS_URL);

    await expect(attachButton(page, UNLINKED)).toHaveCount(1);
    await attachButton(page, UNLINKED).click();
    await page.getByRole("button", { name: GUILD }).click();

    const row = facilitatorRow(page, UNLINKED);
    await expect(row.getByRole("img", { name: `Guild: ${GUILD}` })).toBeVisible();
    await expect(row).toContainText(GUILD);
    await expect(attachButton(page, UNLINKED)).toHaveCount(0);
  });

  test("the plus stays out of the way until the row is hovered or focused", async ({ page }) => {
    await createGuild(page);
    await page.goto(FACILITATORS_URL);
    // A navigation leaves the cursor wherever the last click was, which may
    // well be over the table — park it off the rows first.
    await page.mouse.move(0, 0);
    const plus = attachButton(page, LINKED);

    await expect(plus).toHaveCSS("opacity", "0");

    await facilitatorRow(page, LINKED).hover();
    await expect(plus).toHaveCSS("opacity", "1");

    // Keyboard users never hover, so focus has to reveal it too.
    await page.mouse.move(0, 0);
    await expect(plus).toHaveCSS("opacity", "0");
    await plus.focus();
    await expect(plus).toHaveCSS("opacity", "1");
  });

  test("a manager attaches a facilitator to a guild from the list", async ({ page }) => {
    await createGuild(page);
    await page.goto(FACILITATORS_URL);
    await attachButton(page, LINKED).click();

    // A sphere with no guilds yet still gets a way forward.
    await expect(page.getByRole("link", { name: "New guild" })).toBeVisible();
    await page.getByRole("button", { name: GUILD }).click();

    // Back on the list we posted from, filters and all — not the guild page.
    await expect(page).toHaveURL(FACILITATORS_URL);
    const row = facilitatorRow(page, LINKED);
    await expect(row.getByRole("img", { name: `Guild: ${GUILD}` })).toBeVisible();
    await expect(row).toContainText(GUILD);
    // The way in is gone once there is a guild to show.
    await expect(attachButton(page, LINKED)).toHaveCount(0);
  });

  test("the facilitator's detail page names her guild and links to it", async ({ page }) => {
    await createGuild(page);
    await page.goto(FACILITATORS_URL);
    await attachButton(page, LINKED).click();
    await page.getByRole("button", { name: GUILD }).click();
    await expect(facilitatorRow(page, LINKED)).toContainText(GUILD);

    await facilitatorRow(page, LINKED).getByRole("link", { name: LINKED, exact: true }).click();

    await expect(page.getByRole("heading", { name: LINKED })).toBeVisible();
    await page.getByRole("link", { name: GUILD }).click();
    await expect(page.getByLabel("Guild name")).toHaveValue(GUILD);
  });

  test("a manager adds an imported presenter by the name on the programme", async ({ page }) => {
    await createGuild(page);
    await guildRow(page).getByRole("link", { name: "Edit" }).click();

    await expect(
      page.getByText(
        "Imported presenters have no account — pick them by the name on the programme.",
      ),
    ).toBeVisible();
    await expect(
      page.locator("#guild-presenter-suggestions").locator("option[value='Bob Chen']"),
    ).toHaveCount(1);

    await page.getByLabel("Name, email or Discord username").fill(UNLINKED);
    await page.getByRole("button", { name: "Add presenter" }).click();

    await expect(page.getByText("Presenter added.")).toBeVisible();
    const roster = page.getByRole("listitem").filter({ hasText: UNLINKED });
    await expect(roster.first()).toBeVisible();
    await page.reload();
    await expect(roster.first()).toBeVisible();
  });

  test("a manager attaches a guild from the facilitator edit page", async ({ page }) => {
    await createGuild(page);
    await page.goto(UNLINKED_EDIT_URL);

    const plus = page.getByRole("button", { name: `Attach ${UNLINKED} to a guild` });
    await expect(plus).toBeVisible();
    await expect(plus).toHaveCSS("opacity", "1");
    await plus.click();
    await page.getByRole("button", { name: GUILD }).click();

    await expect(page.getByText("Attached to this guild.")).toBeVisible();
    await expect(page.getByRole("link", { name: GUILD })).toBeVisible();
    await expect(plus).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("link", { name: GUILD })).toBeVisible();
  });

  test("a facilitator with no guild reads as one on her detail page", async ({ page }) => {
    await page.goto(FACILITATORS_URL);
    await facilitatorRow(page, UNLINKED).getByRole("link", { name: UNLINKED, exact: true }).click();

    // The <dt> label's own <dd> — the page is a definition list of details.
    const guildValue = page
      .getByText("Guild", { exact: true })
      .locator("xpath=following-sibling::dd[1]");
    await expect(guildValue).toHaveText("—");
  });
});
