import { expect, test } from "./helpers/fixtures";

const DASHBOARD_URL = "/panel/event/harbour-days/timetable/confirmations/";

// The specs tick real checkboxes on the seeded `harbour-days` event, so they
// run in order and share one worker.
test.describe.configure({ mode: "serial" });

async function login(page) {
  await page.goto("/admin/login/");
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
}

// The dashboard's track row is the way in: clicking it is what an organizer
// does after reading which block is behind.
async function openMainProgramme(page) {
  await page.goto(DASHBOARD_URL);
  await page.getByRole("link", { name: "Main Programme" }).click();
  await expect(page.getByText("Ada McCall")).toBeVisible();
}

function card(page, name: string) {
  return page.locator("details").filter({ has: page.getByText(name, { exact: true }) });
}

test.describe("Confirmations", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("dashboard reports progress and the sessions nobody facilitates", async ({ page }) => {
    await page.goto(DASHBOARD_URL);

    await expect(page.getByRole("heading", { name: "Confirmations" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "By organizer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "By track" })).toBeVisible();
    await expect(page.getByText(/has no facilitator/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Main Programme" })).toBeVisible();

    await page.screenshot({
      path: "test-results/confirmations-dashboard.png",
      fullPage: true,
    });
  });

  test("a fully confirmed facilitator starts folded, an unfinished one open", async ({ page }) => {
    await openMainProgramme(page);

    await expect(card(page, "Ada McCall")).toHaveAttribute("open", "");
    await expect(card(page, "Ben Oyelaran")).not.toHaveAttribute("open", "");

    await page.screenshot({
      path: "test-results/confirmations-track.png",
      fullPage: true,
    });
  });

  test("statuses group the program, and unplaced items carry no checkbox", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");

    await expect(ada.getByText("Scheduled").first()).toBeVisible();
    await expect(ada.getByText("On hold")).toBeVisible();
    await expect(ada.getByText("Rejected")).toBeVisible();

    // Confirmed and unconfirmed sit in the same status group: ticking one must
    // not move it anywhere.
    const scheduled = ada.locator("input[type=checkbox]");
    await expect(scheduled).toHaveCount(3);

    // On hold and rejected are listed, but there is nothing to tick on them.
    const onHoldRow = ada
      .locator("div")
      .filter({ hasText: /^Maybe: Harbour Larp/ })
      .first();
    await expect(onHoldRow.locator("input[type=checkbox]")).toHaveCount(0);
  });

  test("counted states never appear as rows", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");

    await expect(ada.getByText("Undecided Proposal")).toHaveCount(0);
    await expect(ada.getByText("Awaiting A Room")).toHaveCount(0);
    await expect(ada.getByText(/awaits a decision/)).toBeVisible();
    await expect(ada.getByText(/no place in the schedule yet/)).toBeVisible();
  });

  test("a session from another block carries that block's name", async ({ page }) => {
    await openMainProgramme(page);

    await expect(
      card(page, "Ada McCall").getByText("Side Programme", { exact: true }),
    ).toBeVisible();
  });

  test("ticking a checkbox swaps the card and moves the counter", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");
    await expect(ada.getByText("1/3", { exact: true })).toBeVisible();

    const wizards = ada
      .locator("form")
      .filter({ has: page.locator("input[name=agenda_item_pk]") })
      .nth(1);
    await wizards.locator("input[type=checkbox]").check();

    await expect(ada.getByText("2/3", { exact: true })).toBeVisible();
  });

  test("unticking gives the confirmation back", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");
    await expect(ada.getByText("2/3", { exact: true })).toBeVisible();

    const wizards = ada
      .locator("form")
      .filter({ has: page.locator("input[name=agenda_item_pk]") })
      .nth(1);
    await wizards.locator("input[type=checkbox]").uncheck();

    await expect(ada.getByText("1/3", { exact: true })).toBeVisible();
  });

  test("confirming everything folds the card", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");

    await ada.getByRole("button", { name: "Confirm everything" }).click();

    await expect(ada.getByText("3/3", { exact: true })).toBeVisible();
    await expect(ada).not.toHaveAttribute("open", "");
  });

  test("copying an address hands over its scheduled program, without the pending one", async ({
    page,
    context,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");
    await ada.locator("summary").click();

    await ada.getByRole("button", { name: "Copy details" }).first().click();

    const copied = await page.evaluate(() => navigator.clipboard.readText());
    expect(copied).toContain("ada.harbour@example.com");
    expect(copied).toContain("Dragons of the Harbour");
    expect(copied).toContain("Lighthouse Room");
    expect(copied).not.toContain("Undecided Proposal");
    expect(copied).not.toContain("Maybe: Harbour Larp");
  });

  // The dashboard's track links are plain hrefs, so only the switcher proves
  // the select still submits — an inline onchange did not, under the
  // enforcing CSP, and left both directions dead.
  test("the track switcher opens a block and gives the dashboard back", async ({ page }) => {
    await page.goto(DASHBOARD_URL);
    const track = page.getByLabel("Track:");
    const value = await track
      .locator("option", { hasText: "Main Programme" })
      .getAttribute("value");

    await track.selectOption(value);

    await expect(page).toHaveURL(new RegExp(`[?&]track=${value}`));
    await expect(page.getByText("Ada McCall")).toBeVisible();

    await page.getByLabel("Track:").selectOption("");

    await expect(page.getByRole("heading", { name: "By track" })).toBeVisible();
  });

  test("an unclaimed facilitator can be taken on from the list", async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");
    await ada.locator("summary").click();

    await ada.getByRole("button", { name: "Take this on" }).click();

    await expect(page).toHaveURL(/confirmations/);
    await expect(page.getByText(/Handled by/).first()).toBeVisible();
  });
});
