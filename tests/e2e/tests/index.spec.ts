import { expect, test } from "@playwright/test";

test.describe("Event index", () => {
  test("lists upcoming and past events and links to event detail", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Upcoming events" })).toBeVisible();
    const upcomingCard = page.getByRole("link", { name: /Autumn Open Playtest/ });
    await expect(upcomingCard).toContainText("A cozy meetup packed with prototypes");

    await expect(page.getByRole("heading", { name: "Past events" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Retro Mini Jam/ })).toBeVisible();

    await upcomingCard.click();
    await expect(page).toHaveURL(/\/chronology\/event\/autumn-open\//);
    await expect(page.getByRole("heading", { name: "Autumn Open Playtest" })).toBeVisible();
  });
});
