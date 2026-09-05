import { expect, test } from "./helpers/fixtures";

// bootstrap_data.py seats the tester in "Finished Session Demo" on Last
// Year's Convention, so its event page opens on the signed-up banner.
const EVENT_URL = "/event/past-convention/";
const TITLE = "Finished Session Demo";

test.describe("The signed-up banner", () => {
  test("names each session with its day and time, and opens its modal", async ({ page }) => {
    await page.goto(EVENT_URL);

    const banner = page.getByText("You're signed up for 1 session!").locator("xpath=..");
    const link = banner.getByRole("link", { name: TITLE });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("aria-haspopup", "dialog");
    // The row prints the session's day and time range after the link. Shape,
    // not digits: the seed places the session relative to the run date.
    const row = link.locator("xpath=..");
    const rowText = (await row.innerText()).replace(/\s+/g, " ");
    expect(rowText).toMatch(
      new RegExp(`${TITLE} · \\S+, \\d+ \\S+ · \\d{1,2}:\\d{2}–\\d{1,2}:\\d{2}`),
    );

    await link.click();
    await expect(page.getByRole("dialog", { name: TITLE })).toBeVisible();
    await expect(page).toHaveURL(/\?session=\d+$/);
  });
});
