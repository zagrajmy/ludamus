import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// The seeded tester organizes "Backyard Tactics Night" on the root sphere
// (bootstrap_data.py); the seeded manager manages that sphere's events.
test.describe("Command menu for a signed-in member", () => {
  test("offers what they may create and finds an encounter they organize", async ({ page }) => {
    await page.goto("/dashboard/");
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });

    await expect(menu.getByRole("group", { name: "Create" }).getByRole("option")).toHaveText([
      "Create encounter",
    ]);
    // Their encounters wait until something is typed.
    await expect(menu.getByRole("group", { name: "Your encounters" })).toBeHidden();
    await expect(menu.getByRole("group", { name: "Events in the panel" })).toBeHidden();

    await menu.getByRole("combobox").fill("backyard");
    await menu
      .getByRole("group", { name: "Your encounters" })
      .getByRole("option", { name: /Backyard Tactics Night/ })
      .click();

    await expect(page).toHaveURL(/\/e\/[^/]+\/$/);
    await expect(page.getByRole("heading", { name: "Backyard Tactics Night" })).toBeVisible();
  });

  test("starts a new encounter", async ({ page }) => {
    await page.goto("/dashboard/");
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("create enc");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/encounters\/create\/$/);
  });

  // The editor used to keep this shortcut for inserting a link.
  test("opens from inside the markdown editor too", async ({ page }) => {
    await page.goto("/encounters/create/");
    const description = page.getByLabel("Description");
    await description.fill("dice");
    await page.keyboard.press("ControlOrMeta+k");

    await expect(page.getByRole("dialog", { name: "Command menu" })).toBeVisible();
    await expect(description).toHaveValue("dice");
  });

  test("still works, and says what is missing, when its entries fail to load", async ({ page }) => {
    await page.route("**/command-menu/", (route) => route.abort());
    await page.goto("/dashboard/");
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });

    await expect(menu.getByRole("option", { name: "Your dashboard" })).toBeVisible();
    await menu.getByRole("combobox").fill("backyard");
    await expect(
      menu.getByText("Your events and encounters did not load. Reload the page to search them."),
    ).toBeVisible();
  });
});

test.describe("Command menu for an organizer", () => {
  test.use({ storageState: managerState });

  test("finds an event by a folded piece of its name and opens it in the panel", async ({
    page,
  }) => {
    await page.goto("/");
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });

    await menu.getByRole("combobox").fill("miedzynarodowy");
    const events = menu.getByRole("group", { name: "Events in the panel" });
    await expect(events.getByRole("option")).toHaveText([/Międzynarodowy Festiwal Gier/]);
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/panel\/event\/[^/]+\/$/);
  });
});
