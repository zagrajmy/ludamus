import { expect, test } from "@playwright/test";

// Facilitator + proposal CRUD against the dedicated, otherwise-untouched
// "Frostfire Game Convention" panel-lab event (bootstrap_data.py). A proposal
// cannot be created without a facilitator, so the steps build on each other and
// run serially in one shared browser context, leaving new rows behind — this
// event nothing else reads, so that is fine.
test.describe.configure({ mode: "serial" });

const EVENT = "frostfire-con";
const FACILITATORS_URL = `/panel/event/${EVENT}/facilitators/`;
const PROPOSALS_URL = `/panel/event/${EVENT}/proposals/`;

const PROPOSAL_TITLE = "Midnight Heist One-Shot";
const PROPOSAL_TITLE_EDITED = "Midnight Heist One-Shot (revised)";

// Serial retries re-run the whole group from the top (Playwright semantics),
// so a hardcoded name here would leave a duplicate row behind whenever the
// first attempt died after the facilitator was already created — every later
// name-based lookup would then match 2+ elements and fail strict mode. Keep
// the name unique per attempt instead.
let facilitator = "Wanda Frost";

test.describe("Panel facilitator + proposal CRUD", () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate as the sphere manager via Django admin, mirroring the
    // other panel specs.
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("creates a facilitator", async ({ page }, testInfo) => {
    facilitator = testInfo.retry === 0 ? "Wanda Frost" : `Wanda Frost (retry ${testInfo.retry})`;

    await page.goto(FACILITATORS_URL);
    await page.getByRole("link", { name: "New Facilitator" }).click();

    await page.getByLabel("Display Name").fill(facilitator);
    await page.getByLabel("Accreditation type").selectOption({ label: "Standard" });
    await page.getByRole("button", { name: "Create Facilitator" }).click();

    // Redirects back to the list with the new facilitator present.
    await page.waitForURL(/\/facilitators\/$/);
    await page.getByRole("link", { name: facilitator }).click();

    // Detail page shows the cached name and the accreditation we picked.
    await expect(page.getByRole("heading", { name: facilitator })).toBeVisible();
    await expect(page.getByText("Standard")).toBeVisible();
  });

  test("edits the facilitator accreditation", async ({ page }) => {
    await page.goto(FACILITATORS_URL);
    await page.getByRole("link", { name: facilitator }).click();
    // The detail page carries two "Edit" links (header button + the empty
    // personal-data hint); the header one comes first in the DOM.
    await page.getByRole("link", { name: "Edit" }).first().click();

    await page.getByLabel("Accreditation type").selectOption({ label: "Guest" });
    await page.getByRole("button", { name: "Save" }).click();

    // Save redirects straight to the facilitator detail page, which now
    // reflects the new accreditation.
    await page.waitForURL(/\/facilitators\/[^/]+\/$/);
    await expect(page.getByText("Guest")).toBeVisible();
  });

  test("creates a proposal bound to the facilitator", async ({ page }) => {
    await page.goto(PROPOSALS_URL);
    // Header button + empty-state CTA both read "Create Session"; take the
    // header one.
    await page.getByRole("link", { name: "Create Session" }).first().click();

    // The picker is search-first: rows stay hidden until the search matches.
    await page.getByPlaceholder("Search by name…").fill(facilitator);
    await page.getByRole("checkbox", { name: facilitator }).check();
    await page.getByLabel("Category").selectOption({ label: "RPG Proposals" });
    await page.getByLabel("Title").fill(PROPOSAL_TITLE);
    await page.getByLabel("Display Name").fill(facilitator);
    await page.getByRole("button", { name: "Create" }).click();

    // Lands on the new proposal's detail page: pending, with our title.
    await page.waitForURL(new RegExp(`/proposals/\\d+/$`));
    await expect(page.getByRole("heading", { name: PROPOSAL_TITLE })).toBeVisible();
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();
  });

  test("edits the proposal title", async ({ page }) => {
    await page.goto(PROPOSALS_URL);
    await page.getByRole("link", { name: PROPOSAL_TITLE, exact: true }).click();
    await page.getByRole("link", { name: "Edit" }).click();

    await page.getByLabel("Title").fill(PROPOSAL_TITLE_EDITED);
    await page.getByRole("button", { name: "Save" }).click();

    await page.waitForURL(new RegExp(`/proposals/\\d+/$`));
    await expect(page.getByRole("heading", { name: PROPOSAL_TITLE_EDITED })).toBeVisible();
  });

  test("accepts, holds, then rejects the proposal", async ({ page }) => {
    await page.goto(PROPOSALS_URL);
    await page.getByRole("link", { name: PROPOSAL_TITLE_EDITED, exact: true }).click();

    // Accept: no confirmation, badge flips to "Accepted".
    await page.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByText("Accepted", { exact: true })).toBeVisible();

    // Hold: no confirmation, badge flips to "On hold".
    await page.getByRole("button", { name: "Hold" }).click();
    await expect(page.getByText("On hold", { exact: true })).toBeVisible();

    // Reject: guarded by a confirm dialog, then badge flips to "Rejected".
    await page.getByRole("button", { name: "Reject" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Reject" }).click();
    await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
  });
});
