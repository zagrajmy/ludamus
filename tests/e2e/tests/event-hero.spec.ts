import { expect, test } from "./helpers/fixtures";

test.describe("Small event hero", () => {
  test("keeps session stats and has no program CTAs", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    const hero = page.locator("[data-event-hero]");
    await expect(hero.getByRole("link", { name: "View the program" })).toHaveCount(0);
    await expect(hero.getByRole("link", { name: "Sign up for sessions" })).toHaveCount(0);
    await expect(hero.getByText("Players", { exact: true })).toBeVisible();
  });
});

test.describe("Big event hero", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/kapitularz-2025-anonymized/");
  });

  test("offers browse then sign-up, without a participant count", async ({ page }) => {
    const hero = page.locator("[data-event-hero]");
    const viewProgram = hero.getByRole("link", { name: "View the program" });
    const signUp = hero.getByRole("link", { name: "Sign up for sessions" });

    await expect(viewProgram).toBeVisible();
    await expect(signUp).toBeVisible();
    await expect(viewProgram).toHaveAttribute("href", "#schedule-region");
    await expect(signUp).toHaveAttribute("href", "?enrollment=1#schedule-region");
    await expect(hero.getByText("Players", { exact: true })).toHaveCount(0);
    await expect(hero.getByText("Participants", { exact: true })).toHaveCount(0);
    await expect(hero.getByText(/\d+\s+Sessions/)).toBeVisible();
  });

  test("links the venue address to Google Maps", async ({ page }) => {
    const hero = page.locator("[data-event-hero]");
    const address = hero.getByRole("link", { name: /4 Assembly Concourse/ });

    await expect(address).toBeVisible();
    await expect(address).toHaveAttribute(
      "href",
      /google\.com\/maps\/search\/\?api=1&query=4%20Assembly/,
    );
  });

  test("the date opens an add-to-calendar menu", async ({ page }) => {
    const hero = page.locator("[data-event-hero]");
    await hero.getByRole("button", { name: /10:00/ }).hover();

    const googleCalendar = hero.getByRole("link", { name: "Google Calendar" });
    await expect(googleCalendar).toBeVisible();
    await expect(googleCalendar).toHaveAttribute(
      "href",
      /calendar\.google\.com\/calendar\/render\?action=TEMPLATE/,
    );
    await expect(hero.getByRole("link", { name: "Other calendars (.ics)" })).toHaveAttribute(
      "href",
      /\/calendar\.ics$/,
    );
  });

  test("viewing the program jumps to the schedule", async ({ page }) => {
    await page.getByRole("link", { name: "View the program" }).click();
    await expect(page.locator("#schedule-region")).toBeInViewport();
  });

  test("signing up for sessions filters to enrollable ones", async ({ page }) => {
    await page.getByRole("link", { name: "Sign up for sessions" }).click();

    await expect(page).toHaveURL(/enrollment=1/);
    await expect(page.getByRole("checkbox", { name: "Only with enrollment" })).toBeChecked();
    await expect(page.locator("#schedule-region")).toBeInViewport();
  });
});
