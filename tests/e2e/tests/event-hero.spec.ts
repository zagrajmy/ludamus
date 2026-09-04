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

  test("the calendar menu stays open across the hover gap and closes on Escape", async ({
    page,
  }) => {
    const hero = page.locator("[data-event-hero]");
    const trigger = hero.getByRole("button", { name: /10:00/ });
    const googleCalendar = hero.getByRole("link", { name: "Google Calendar" });

    await trigger.hover();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(googleCalendar).toBeVisible();

    const target = await googleCalendar.boundingBox();
    if (!target) throw new Error("calendar menu item has no box");
    await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, {
      steps: 10,
    });
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    await page.keyboard.press("Escape");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(googleCalendar).toBeHidden();
  });

  test("viewing the program jumps to the schedule", async ({ page }) => {
    await page.getByRole("link", { name: "View the program" }).click();
    await expect(page.locator("#schedule-region")).toBeInViewport();
  });

  test("signing up for sessions filters to enrollable ones", async ({ page }) => {
    const enrollmentNavs: string[] = [];
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.url().includes("enrollment=")) {
        enrollmentNavs.push(request.url());
      }
    });

    await page.getByRole("link", { name: "Sign up for sessions" }).click();

    await expect(page).toHaveURL(/enrollment=1/);
    await expect(page.getByRole("checkbox", { name: "Only with enrollment" })).toBeChecked();
    await expect(page.locator("#schedule-region")).toBeInViewport();
    expect(enrollmentNavs).toEqual([]);
  });

  // Clear of 640 itself: the row starts exactly at the sm breakpoint, and a
  // test sitting on the boundary would answer a scrollbar rather than a layout.
  test("hero CTAs stay in a row when they fit below the md breakpoint", async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 800 });
    const hero = page.locator("[data-event-hero]");
    const viewBox = await hero.getByRole("link", { name: "View the program" }).boundingBox();
    const signBox = await hero.getByRole("link", { name: "Sign up for sessions" }).boundingBox();
    if (!viewBox || !signBox) throw new Error("hero CTA has no box");
    expect(Math.abs(viewBox.y - signBox.y)).toBeLessThan(8);
  });

  // A wrapping row left ragged half-rows whose icons lined up with nothing.
  test("stacks the facts on one rail on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const hero = page.locator("[data-event-hero]");
    const date = await hero.getByRole("button", { name: /10:00/ }).boundingBox();
    const address = await hero.getByRole("link", { name: /4 Assembly Concourse/ }).boundingBox();
    if (!date || !address) throw new Error("hero fact has no box");

    expect(address.y).toBeGreaterThan(date.y + date.height);
    expect(Math.abs(address.x - date.x)).toBeLessThan(1);
  });

  // Which of the two the phone gets depends on the labels' own widths, so the
  // viewports here sit clear of the turn rather than on it.
  test("gives the CTAs equal widths whether they share a row or stack", async ({ page }) => {
    const hero = page.locator("[data-event-hero]");
    const view = hero.getByRole("link", { name: "View the program" });
    const sign = hero.getByRole("link", { name: "Sign up for sessions" });
    const boxes = async () => {
      const [v, s] = [await view.boundingBox(), await sign.boundingBox()];
      if (!v || !s) throw new Error("hero CTA has no box");
      return [v, s] as const;
    };

    await page.setViewportSize({ width: 480, height: 900 });
    const [wideView, wideSign] = await boxes();
    expect(Math.abs(wideView.y - wideSign.y)).toBeLessThan(1);
    expect(Math.abs(wideView.width - wideSign.width)).toBeLessThan(1);

    await page.setViewportSize({ width: 390, height: 900 });
    const [narrowView, narrowSign] = await boxes();
    expect(narrowSign.y).toBeGreaterThan(narrowView.y + narrowView.height);
    expect(Math.abs(narrowView.width - narrowSign.width)).toBeLessThan(1);
    expect(Math.abs(narrowView.x - narrowSign.x)).toBeLessThan(1);
  });

  // Full bleed on a phone: a cover that tall reads as the page's header, not
  // as a photo on a floating tile, and the body picks up the page's gutter.
  test("runs the hero edge to edge on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    const hero = page.locator("[data-event-hero]");
    const box = await hero.boundingBox();
    const main = await page.locator("main").boundingBox();
    if (!box || !main) throw new Error("hero has no box");

    // Out past the gutter `main` keeps, to the width of the whole column.
    expect(Math.abs(box.x - main.x)).toBeLessThan(1);
    expect(Math.abs(box.width - main.width)).toBeLessThan(1);
    await expect(hero).toHaveCSS("border-top-left-radius", "0px");
  });
});
