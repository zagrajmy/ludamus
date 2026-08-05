import { expect, test } from "./helpers/fixtures";

test.describe("Landing", () => {
  test("greets organizers on the root domain and switches to the player view", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle("Zagrajmy • conventions and events");
    await expect(page.getByRole("heading", { name: /Run a conference or meetup/ })).toBeVisible();

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
    await expect(page.getByRole("heading", { name: /Run a conference or meetup/ })).toBeHidden();
  });

  test("keeps the plain event listing on /events/", async ({ page }) => {
    await page.goto("/events/");

    await expect(page.getByRole("heading", { name: "Upcoming events" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Run a conference or meetup/ })).toBeHidden();
  });
});
