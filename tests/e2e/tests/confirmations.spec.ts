import { expect, test } from "./helpers/fixtures";

const DASHBOARD_URL = "/panel/event/harbour-days/timetable/confirmations/";

// The specs tick real checkboxes on the seeded `harbour-days` event, so they
// share one worker and run in order. Nothing re-seeds between attempts —
// bootstrap_confirmations.py is get_or_create throughout — so an afterEach puts
// the seeded state back whether the test passed or failed, and a serial retry
// re-runs the block against the state it expects.
test.describe.configure({ mode: "serial" });

// The one placed session the seed leaves confirmed; the other two start clear.
const SEEDED_CONFIRMATIONS: [string, boolean][] = [
  ["Dragons of the Harbour", true],
  ["Wizards of the Pier", false],
  ["Club Night", false],
];

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

// A card renders folded only while its facilitator is fully confirmed, so
// unfolding one has to be conditional: a blind summary click closes the rest.
// The restore hook can reach a card an HTMX swap is still replacing, hence the
// polling waits around the one-shot attribute read.
async function unfold(facilitatorCard) {
  await expect(facilitatorCard).toBeVisible();
  if ((await facilitatorCard.getAttribute("open")) === null) {
    await facilitatorCard.locator("summary").click();
    await expect(facilitatorCard).toHaveAttribute("open", "");
  }
}

function card(page, name: string) {
  return page.locator("details").filter({ has: page.getByText(name, { exact: true }) });
}

// A row's text opens with its session title — after the template's own
// indentation, which `hasText` hands to a regex unnormalized — so an anchored
// match lands on the row and not on the status group or the card above it.
// Naming the row keeps a restore off checkbox position, which only ever lined
// up by accident of the seed's start hours and email ordering.
function row(facilitatorCard, title: string) {
  return facilitatorCard
    .locator("div")
    .filter({ hasText: new RegExp(`^\\s*${title}`) })
    .first();
}

test.describe("Confirmations", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  // Every mutation these specs make is Ada's, and each undo is a no-op when the
  // test did not get that far — so one hook restores from any state, including
  // the state a failed assertion left behind.
  test.afterEach(async ({ page }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");

    const stepDown = ada.getByRole("button", { name: "Step down" });
    if (await stepDown.count()) {
      await stepDown.click();
      await expect(ada.getByText("Nobody handles this facilitator")).toBeVisible();
    }

    await unfold(ada);
    let confirmed = await ada.locator("input[type=checkbox]:checked").count();
    for (const [title, seeded] of SEEDED_CONFIRMATIONS) {
      const box = row(ada, title).locator("input[type=checkbox]");
      if ((await box.isChecked()) === seeded) {
        continue;
      }
      await box.setChecked(seeded);
      confirmed += seeded ? 1 : -1;
      // The counter is the swap landing: waiting on it keeps the next undo off
      // a card that is about to be replaced.
      await expect(ada.getByText(`${confirmed}/3`, { exact: true })).toBeVisible();
    }
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
    await expect(row(ada, "Maybe: Harbour Larp").locator("input[type=checkbox]")).toHaveCount(0);
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

  test("ticking a checkbox moves the counter, unticking gives the confirmation back", async ({
    page,
  }) => {
    await openMainProgramme(page);
    const ada = card(page, "Ada McCall");
    await expect(ada.getByText("1/3", { exact: true })).toBeVisible();

    const wizards = row(ada, "Wizards of the Pier").locator("input[type=checkbox]");
    await wizards.check();

    await expect(ada.getByText("2/3", { exact: true })).toBeVisible();

    await wizards.uncheck();

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

    await ada.getByRole("button", { name: "Take this on" }).click();

    await expect(page).toHaveURL(/confirmations/);
    await expect(page.getByText(/Handled by/).first()).toBeVisible();
  });
});
