import { expect, test } from "./helpers/fixtures";

// A bare proposals URL means "pending backlog", so "All statuses" only holds
// if every form and link on the page carries it back. These specs cover the
// two paths that can silently drop it: the separate track form in the header,
// and the Clear link.
const PROPOSALS_URL = "/panel/event/sunhaven-festival/proposals/";

test.describe("Proposal status filter", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("opens on the pending backlog", async ({ page }) => {
    await page.goto(PROPOSALS_URL);

    await expect(page.getByLabel("Status")).toHaveValue("pending");
  });

  test('keeps "All statuses" when the track filter submits', async ({ page }) => {
    await page.goto(PROPOSALS_URL);

    await page.getByLabel("Status").selectOption("all");
    await expect(page).toHaveURL(/[?&]status=all/);

    // The track switcher is a second, separate GET form — it has to echo the
    // status back or the absent-param default re-selects pending.
    await page.getByLabel("Track").selectOption("multi");
    await expect(page).toHaveURL(/[?&]track=multi/);
    await expect(page.getByLabel("Status")).toHaveValue("all");
  });

  test("empty filtered list offers a way back to every status", async ({ page }) => {
    // Nothing is on hold in this event, so the list comes back empty — the
    // organizer needs an escape hatch that isn't the status select itself.
    await page.goto(`${PROPOSALS_URL}?status=on_hold`);
    await expect(page.getByText("No proposals match the current filters.")).toBeVisible();

    await page.getByRole("link", { name: "Show all statuses" }).click();

    await expect(page.getByLabel("Status")).toHaveValue("all");
  });

  test("Clear drops the filters instead of applying the pending default", async ({ page }) => {
    await page.goto(`${PROPOSALS_URL}?status=rejected`);
    await expect(page.getByLabel("Status")).toHaveValue("rejected");

    await page.getByRole("link", { name: "Clear" }).click();

    await expect(page.getByLabel("Status")).toHaveValue("all");
  });
});
