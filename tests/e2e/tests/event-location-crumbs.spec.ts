import { expect, test } from "./helpers/fixtures";

test.describe("Location breadcrumbs", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/autumn-open/");
  });

  test("card crumbs link the floor and the room, not the building", async ({ page }) => {
    const card = page.getByRole("article").filter({ hasText: "Mega Strategy Lab" });
    const session = card.locator(".session");
    const venue = await session.getAttribute("data-venue");
    const space = await session.getAttribute("data-space");
    if (!venue || !space) throw new Error("Mega Strategy Lab has no venue or space");

    await expect(card.getByRole("link", { name: "Convention Center" })).toHaveCount(0);
    await expect(card.getByRole("link", { name: "Main Hall" })).toHaveAttribute(
      "href",
      new RegExp(`/event/autumn-open/\\?space=venue:${venue}#schedule-region$`),
    );
    await expect(card.getByRole("link", { name: "East Wing" })).toHaveAttribute(
      "href",
      new RegExp(`/event/autumn-open/\\?space=${space}#schedule-region$`),
    );
  });

  test("clicking a floor crumb filters to every room on that floor", async ({ page }) => {
    const card = page.getByRole("article").filter({ hasText: "Mega Strategy Lab" });
    const venue = await card.locator(".session").getAttribute("data-venue");
    if (!venue) throw new Error("Mega Strategy Lab has no venue");

    const spaceNavs: string[] = [];
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.url().includes("space=")) {
        spaceNavs.push(request.url());
      }
    });

    await card.getByRole("link", { name: "Main Hall" }).click();

    await expect.poll(() => new URL(page.url()).searchParams.get("space")).toBe(`venue:${venue}`);
    await expect(page.locator("#space-filter")).toHaveValue(`venue:${venue}`);
    await expect(page.locator("#schedule-region")).toBeInViewport();
    expect(spaceNavs).toEqual([]);

    const visible = page.locator(".session-wrapper:not([hidden])");
    await expect.poll(() => visible.count()).toBeGreaterThan(0);
    for (const session of await visible.locator(".session").all())
      await expect(session).toHaveAttribute("data-venue", venue);
  });

  test("a modal crumb filters the schedule and leaves the map icon on the map", async ({
    page,
  }) => {
    const card = page.getByRole("article").filter({ hasText: "Mega Strategy Lab" });
    const space = await card.locator(".session").getAttribute("data-space");
    if (!space) throw new Error("Mega Strategy Lab has no space");

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
    const dialog = page.getByRole("dialog", { name: "Mega Strategy Lab" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("link", { name: "East Wing" })).toHaveAttribute(
      "href",
      new RegExp(`/event/autumn-open/\\?space=${space}#schedule-region$`),
    );

    await dialog.getByRole("link", { name: "East Wing" }).click();

    await expect(dialog).toBeHidden();
    await expect.poll(() => new URL(page.url()).searchParams.get("space")).toBe(space);
    await expect.poll(() => new URL(page.url()).searchParams.get("session")).toBeNull();
    await expect(page.locator("#space-filter")).toHaveValue(space);

    const visible = page.locator(".session-wrapper:not([hidden])");
    await expect.poll(() => visible.count()).toBeGreaterThan(0);
    for (const session of await visible.locator(".session").all())
      await expect(session).toHaveAttribute("data-space", space);
  });
});
