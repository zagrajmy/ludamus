import { expect, test } from "./helpers/fixtures";

test.describe("Landing", () => {
  test("greets organizers on the root domain and switches to the player view", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle("Zagrajmy • conventions and events");
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeVisible();

    await page.getByText("For players", { exact: true }).filter({ visible: true }).click();

    await expect(page).toHaveURL(/#gracze$/);
    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
    ).toBeVisible();
  });

  test("#gracze deep link opens the player view directly", async ({ page }) => {
    await page.goto("/#gracze");

    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();
  });

  test("keeps the plain feed on a sphere domain, announcements first", async ({ page }) => {
    await page.goto("http://foreign.localhost:8000/");

    await expect(page.getByRole("heading", { name: "Upcoming" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();

    // A sphere's announcements sit above its programme. The root sphere runs
    // no programme and shows none.
    await expect(page.getByRole("heading", { name: "Organization announcements" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Doors open at 9:00" })).toBeVisible();

    // The feed's cards reach their event — coverage that lived in
    // index.spec.ts, against the root domain, which is the pitch now. Located
    // by href: the sphere and its event share a name, so the navbar's brand
    // link answers to the same accessible name.
    await page.locator('#events a[href="/event/foreign-programme/"]').first().click();
    await expect(page).toHaveURL(/\/event\/foreign-programme\//);
  });
});
