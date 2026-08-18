import { type Page } from "@playwright/test";

import { installCspViolationCollector } from "./helpers/csp";
import { assertDropzoneBlobPreview, labeledDropzone, shownFileName } from "./helpers/dropzone";
import { expect, test } from "./helpers/fixtures";

// Both guild-touching suites live in this one serial file on purpose: the
// empty-state test below asserts "No guilds yet.", which is only true while
// ZERO guilds exist in the sphere — a guild held alive by a concurrently
// running file makes it flake. One file + serial mode is the only scheduling
// unit Playwright guarantees never overlaps itself.

// A 1x1 opaque PNG — a mark only has to be a real raster the browser will
// decode, so the smallest valid one keeps the fixture inline.
const PNG_BYTES = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const signInAsManager = async (page: Page): Promise<void> => {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
};

const GUILD = "Topory";
const PRESENTER_EMAIL = "e2e@test.local";

const logoInput = (page: Page) => page.getByLabel("Logo", { exact: true });
const logoDropzone = (page: Page) => labeledDropzone(page, "Logo");

const deleteGuildIfPresent = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/");
  const row = page.getByRole("row").filter({ hasText: GUILD });
  if ((await row.count()) === 0) return;
  await row.getByRole("link", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete guild" }).click();
  await expect(page.getByText("Guild deleted.")).toBeVisible();
};

// The facilitator-marks suite runs against the frostfire-con panel-lab event,
// where bootstrap_facilitators.py seeds Dana Reyes with an account of her own
// and Bob Chen without one — the two states the guild column has to tell
// apart. Its own guild name, so the two suites' cleanups stay independent.
const MARKS_GUILD = "Kuźnia";
const LINKED = "Dana Reyes";
const UNLINKED = "Bob Chen";
const FACILITATORS_URL = "/panel/event/frostfire-con/facilitators/";
const UNLINKED_EDIT_URL = "/panel/event/frostfire-con/facilitators/bob-chen/edit/";

const marksGuildRow = (page: Page) => page.getByRole("row").filter({ hasText: MARKS_GUILD });

// Deleting the guild takes its memberships with it, so this resets the mark on
// the facilitator too.
const deleteMarksGuildIfPresent = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/");
  if ((await marksGuildRow(page).count()) === 0) return;
  await marksGuildRow(page).getByRole("link", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete guild" }).click();
  // The row itself, not the "Guild deleted." toast: transient flashes clear
  // themselves after five seconds, which a slow page load can outlast.
  await expect(marksGuildRow(page)).toHaveCount(0);
};

const createMarksGuild = async (page: Page): Promise<void> => {
  await page.goto("/multiverse/panel/guilds/create/");
  await page.getByLabel("Guild name").fill(MARKS_GUILD);
  await page.getByLabel("Logo", { exact: true }).setInputFiles({
    name: "mark.png",
    mimeType: "image/png",
    buffer: PNG_BYTES,
  });
  await page.getByRole("button", { name: "Create guild" }).click();
  await expect(marksGuildRow(page)).toBeVisible();
};

const facilitatorRow = (page: Page, name: string) =>
  page.getByRole("row").filter({ hasText: name });

const attachButton = (page: Page, name: string) =>
  facilitatorRow(page, name).getByRole("button", { name: `Attach ${name} to a guild` });

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
    await installCspViolationCollector(page);
    await page.goto("/multiverse/panel/guilds/create/");

    await page.getByLabel("Guild name").fill(GUILD);
    await logoInput(page).setInputFiles({
      name: "mark.png",
      mimeType: "image/png",
      buffer: PNG_BYTES,
    });
    await expect(shownFileName(logoDropzone(page), "mark.png")).toBeVisible();
    await assertDropzoneBlobPreview(page, logoDropzone(page));
    await page.getByRole("button", { name: "Create guild" }).click();

    await expect(page.getByText("Guild created.")).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: GUILD });
    await expect(row).toBeVisible();
    // The mark is an <img> inside the row, so it is the row's own picture
    // rather than the page-level sphere logo.
    await expect(row.locator("img")).toHaveJSProperty("naturalWidth", 1);
  });

  test("clicking a hoverable row opens Edit", async ({ page }) => {
    await page.goto("/multiverse/panel/guilds/create/");
    await page.getByLabel("Guild name").fill(GUILD);
    await page.getByRole("button", { name: "Create guild" }).click();
    await expect(page.getByText("Guild created.")).toBeVisible();

    const row = page.getByRole("row").filter({ hasText: GUILD });
    await row.getByRole("link", { name: "Delete" }).click();
    await expect(page).toHaveURL(/\/multiverse\/panel\/guilds\/\d+\/do\/delete\//);
    await page.getByRole("link", { name: "Cancel" }).click();
    await expect(page).toHaveURL(/\/multiverse\/panel\/guilds\/$/);

    const presentersCell = row.locator("td").nth(1);
    const box = await presentersCell.boundingBox();
    if (box === null) {
      throw new Error("guild row has no box");
    }
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);

    await expect(page).toHaveURL(/\/multiverse\/panel\/guilds\/\d+\/edit\//);
    await expect(page.getByLabel("Guild name")).toHaveValue(GUILD);
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
    await expect(
      page.getByText(
        "Imported presenters have no account — pick them by the name on the programme.",
      ),
    ).toBeVisible();
    await page.getByLabel("Name, email or Discord username").fill(PRESENTER_EMAIL);
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

    await page.getByLabel("Name, email or Discord username").fill("nobody@example.com");
    await page.getByRole("button", { name: "Add presenter" }).click();

    await expect(
      page.getByText("No presenter matches that name, email or Discord username."),
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

    // The site navbar is a <nav> too, so the sidebar is picked by its label.
    const sidebar = page.getByRole("navigation", { name: "Panel sections" });
    const settings = sidebar.getByRole("link", {
      name: "Sphere settings",
      exact: true,
    });
    await expect(settings).toHaveAttribute("aria-current", "page");

    await sidebar.getByRole("link", { name: "Guilds", exact: true }).click();

    await expect(page).toHaveURL(/\/multiverse\/panel\/guilds\/$/);
    await expect(page.getByRole("heading", { name: "Guilds", level: 2 })).toBeVisible();
    // Sphere settings owned the highlight on the page we came from; arriving at
    // Guilds has to move it, which is the whole point of the nav entry.
    await expect(sidebar.getByRole("link", { name: "Guilds", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(settings).not.toHaveAttribute("aria-current", "page");
  });
});

test.describe("Facilitator guild marks", () => {
  test.beforeEach(async ({ page }) => {
    await signInAsManager(page);
    await deleteMarksGuildIfPresent(page);
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await signInAsManager(page);
    await deleteMarksGuildIfPresent(page);
    await page.close();
  });

  test("a facilitator with no account can be attached to a guild", async ({ page }) => {
    await createMarksGuild(page);
    await page.goto(FACILITATORS_URL);

    await expect(attachButton(page, UNLINKED)).toHaveCount(1);
    await attachButton(page, UNLINKED).click();
    await page.getByRole("button", { name: MARKS_GUILD }).click();

    const row = facilitatorRow(page, UNLINKED);
    await expect(row.getByRole("img", { name: `Guild: ${MARKS_GUILD}` })).toBeVisible();
    await expect(row).toContainText(MARKS_GUILD);
    await expect(attachButton(page, UNLINKED)).toHaveCount(0);
  });

  test("the plus stays out of the way until the row is hovered or focused", async ({ page }) => {
    await createMarksGuild(page);
    await page.goto(FACILITATORS_URL);
    // A navigation leaves the cursor wherever the last click was, which may
    // well be over the table — park it off the rows first.
    await page.mouse.move(0, 0);
    const plus = attachButton(page, LINKED);
    const hoverReveal = plus.locator("xpath=../..");

    await expect(hoverReveal).toHaveCSS("opacity", "0");

    await facilitatorRow(page, LINKED).hover();
    await expect(hoverReveal).toHaveCSS("opacity", "1");

    // Keyboard users never hover, so focus has to reveal it too.
    await page.mouse.move(0, 0);
    await expect(hoverReveal).toHaveCSS("opacity", "0");
    await plus.focus();
    await expect(hoverReveal).toHaveCSS("opacity", "1");
  });

  test("a manager attaches a facilitator to a guild from the list", async ({ page }) => {
    await createMarksGuild(page);
    await page.goto(FACILITATORS_URL);
    await attachButton(page, LINKED).click();

    // A sphere with no guilds yet still gets a way forward.
    await expect(page.getByRole("link", { name: "New guild" })).toBeVisible();
    await page.getByRole("button", { name: MARKS_GUILD }).click();

    // Back on the list we posted from, filters and all — not the guild page.
    await expect(page).toHaveURL(FACILITATORS_URL);
    const row = facilitatorRow(page, LINKED);
    await expect(row.getByRole("img", { name: `Guild: ${MARKS_GUILD}` })).toBeVisible();
    await expect(row).toContainText(MARKS_GUILD);
    // The way in is gone once there is a guild to show.
    await expect(attachButton(page, LINKED)).toHaveCount(0);
  });

  test("the facilitator's detail page names her guild and links to it", async ({ page }) => {
    await createMarksGuild(page);
    await page.goto(FACILITATORS_URL);
    await attachButton(page, LINKED).click();
    await page.getByRole("button", { name: MARKS_GUILD }).click();
    await expect(facilitatorRow(page, LINKED)).toContainText(MARKS_GUILD);

    await facilitatorRow(page, LINKED).getByRole("link", { name: LINKED, exact: true }).click();

    await expect(page.getByRole("heading", { name: LINKED })).toBeVisible();
    await page.getByRole("link", { name: MARKS_GUILD }).click();
    await expect(page.getByLabel("Guild name")).toHaveValue(MARKS_GUILD);
  });

  test("a manager adds an imported presenter by the name on the programme", async ({ page }) => {
    await createMarksGuild(page);
    await marksGuildRow(page).getByRole("link", { name: "Edit" }).click();

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
    await createMarksGuild(page);
    await page.goto(UNLINKED_EDIT_URL);

    const plus = page.getByRole("button", { name: `Attach ${UNLINKED} to a guild` });
    await expect(plus).toBeVisible();
    await expect(plus).toHaveCSS("opacity", "1");
    await plus.click();
    await page.getByRole("button", { name: MARKS_GUILD }).click();

    await expect(page.getByText("Attached to this guild.")).toBeVisible();
    await expect(page.getByRole("link", { name: MARKS_GUILD })).toBeVisible();
    await expect(plus).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("link", { name: MARKS_GUILD })).toBeVisible();
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
