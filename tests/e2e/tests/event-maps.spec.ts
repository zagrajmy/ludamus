import { expect, test } from "./helpers/fixtures";

// Walks the whole life of a map on the seeded `retro-mini-jam` event, whose
// space tree is Arcade Hall > Main Arcade Floor > Puzzle Corner. The specs
// mutate shared seed data, so they run serially and clean up after
// themselves; the project config keeps them on chromium only.

const EVENT_URL = "/event/retro-mini-jam/";
const MAPS_URL = `${EVENT_URL}maps/`;

const PNG_BYTES = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010802000000" +
    "907753de0000000c49444154789c63606060000000040001f6173855" +
    "0000000049454e44ae426082",
  "hex",
);

const GIF_BYTES = Buffer.from(
  "47494638376101000100810000ffffff000000000000000000" + "2c000000000100010000080400010404003b",
  "hex",
);

const logInAsManager = async (page: import("@playwright/test").Page) => {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
};

test.describe.configure({ mode: "serial" });

test.describe("Event maps", () => {
  test("a viewer sees the empty state and no organizer controls", async ({ page }) => {
    await page.goto(MAPS_URL);

    await expect(page.getByRole("heading", { name: "Maps", level: 1 })).toBeVisible();
    await expect(page.getByText("The organizers haven't added any maps yet.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Add map" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Back to the program" })).toHaveAttribute(
      "href",
      EVENT_URL,
    );

    // No maps, so the hero offers nothing to open.
    await page.goto(EVENT_URL);
    await expect(
      page.locator("[data-event-hero]").getByRole("link", { name: "Venue maps" }),
    ).toHaveCount(0);
  });

  test("an organizer adds a map, attaches a venue, and the hero links to it", async ({ page }) => {
    await logInAsManager(page);
    await page.goto(MAPS_URL);

    // The "Add map" link opens an addressable dialog.
    await page.getByRole("link", { name: "Add map" }).first().click();
    const addDialog = page.getByRole("dialog", { name: "Add map" });
    await expect(addDialog).toBeVisible();
    await expect(page).toHaveURL(/\?add-map=1$/);

    // A rejected upload reopens the dialog with its error. (An empty one never
    // leaves the browser: the dropzone's input is required.)
    await addDialog.getByRole("textbox", { name: /^Name/ }).fill("Ground floor");
    await addDialog.getByLabel("Map image", { exact: true }).setInputFiles({
      name: "floor.gif",
      mimeType: "image/gif",
      buffer: GIF_BYTES,
    });
    await addDialog.getByRole("button", { name: "Add map" }).click();
    await expect(page.getByRole("dialog", { name: "Add map" })).toBeVisible();
    await expect(
      page.getByText("Unsupported image format. Use JPG, PNG, WebP, or AVIF."),
    ).toBeVisible();

    const reopened = page.getByRole("dialog", { name: "Add map" });
    await reopened.getByLabel("Map image", { exact: true }).setInputFiles({
      name: "floor.png",
      mimeType: "image/png",
      buffer: PNG_BYTES,
    });
    await reopened.getByRole("button", { name: "Add map" }).click();

    await expect(page.getByText("Map added.")).toBeVisible();
    const card = page.locator("section", {
      has: page.getByRole("heading", { name: "Ground floor", level: 2 }),
    });
    await expect(card).toBeVisible();
    await expect(card.getByRole("img", { name: "Ground floor" })).toBeVisible();
    await expect(card.getByRole("link", { name: "Edit Ground floor" })).toBeVisible();
    await expect(card.getByRole("button", { name: "Delete Ground floor" })).toBeVisible();

    // Attaching a room draws it in its venue's tree; the room links into the
    // schedule filtered to it, the venue above it stays plain text.
    await card.getByRole("link", { name: "Attach venue" }).click();
    const attachDialog = page.getByRole("dialog", { name: "Attach venue" });
    await expect(attachDialog).toBeVisible();
    await attachDialog.getByLabel("Arcade Hall > Main Arcade Floor > Puzzle Corner").check();
    await attachDialog.getByRole("button", { name: "Save venues" }).click();

    await expect(page.getByText("Venues on the map updated.")).toBeVisible();
    const tree = page.getByRole("navigation", { name: "Venues on Ground floor" });
    await expect(tree.getByText("Arcade Hall", { exact: true })).toBeVisible();
    await expect(tree.getByRole("link", { name: "Arcade Hall" })).toHaveCount(0);
    const roomLink = tree.getByRole("link", { name: "Puzzle Corner" });
    await expect(roomLink).toHaveAttribute(
      "href",
      /\/event\/retro-mini-jam\/\?space=\d+#schedule-region$/,
    );

    // The hero now offers the maps page.
    await page.goto(EVENT_URL);
    const heroLink = page.locator("[data-event-hero]").getByRole("link", { name: "Venue maps" });
    await expect(heroLink).toBeVisible();
    await heroLink.click();
    await expect(page).toHaveURL(MAPS_URL);
    await expect(page.getByRole("heading", { name: "Ground floor", level: 2 })).toBeVisible();
  });

  test("an organizer renames and then deletes the map", async ({ page }) => {
    await logInAsManager(page);
    await page.goto(MAPS_URL);

    await page.getByRole("link", { name: "Edit Ground floor" }).click();
    const editDialog = page.getByRole("dialog", { name: "Edit map" });
    await expect(editDialog).toBeVisible();
    await editDialog.getByRole("textbox", { name: /^Name/ }).fill("First floor");
    await editDialog.getByRole("button", { name: "Save map" }).click();

    await expect(page.getByText("Map saved.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "First floor", level: 2 })).toBeVisible();

    await page.getByRole("button", { name: "Delete First floor" }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Confirm" }).click();

    await expect(page.getByText("Map deleted.")).toBeVisible();
    await expect(page.getByText("No maps yet.", { exact: false })).toBeVisible();
    await expect(page.getByRole("heading", { name: "First floor", level: 2 })).toHaveCount(0);
  });
});
