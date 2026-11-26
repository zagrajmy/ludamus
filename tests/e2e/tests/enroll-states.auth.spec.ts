import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// enroll-states seeds two sessions on one open window: one with room, one with
// every seat taken (tests/e2e/scripts/bootstrap_data.py). Between them they pin
// both ways *in*, which no other spec exercises from the modal footer.

const openModal = async (page: Page, title: string) => {
  await page.goto("/event/enroll-states/");
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return { dialog, footer: dialog.locator("[data-session-footer]") };
};

// The window is open here, so whatever a test takes it can give back. Doing it
// in afterEach means a failed assertion mid-test still leaves the seeded state
// as it found it, and a retry tests the feature rather than the leftovers.
const release = async (page: Page, title: string) => {
  const { footer } = await openModal(page, title);
  for (const label of ["Cancel", "Leave"]) {
    const button = footer.getByRole("button", { name: label, exact: true });
    if (await button.count()) {
      await button.click();
      await expect(button).toHaveCount(0);
    }
  }
};

// Both tests act as the same seeded tester on the same event, and the suite is
// fullyParallel with two workers on CI — run in parallel, one test's restore
// would cancel the other's seat mid-assertion. Serial is the house pattern for
// specs that mutate shared seed data (panel, confirmations, timetable, …).
test.describe.configure({ mode: "serial" });

// The enroll view, which the one-click footer posts to.
const ENROLL_POST = "**/session/*/enrollment/";

const capacity = (dialog: ReturnType<Page["getByRole"]>) => dialog.locator("[data-roster]");

test.describe("Ways into a session while enrollment is open", () => {
  // Scoped to the session the test actually touched, so a restore never
  // reaches into a sibling's state.
  test.afterEach(async ({ page }, testInfo) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await release(
      page,
      testInfo.title.includes("full session") ? "Waiting List Only Demo" : "Seat Available Demo",
    );
  });

  test("a session with room offers a seat, and taking it flips to the way out", async ({
    page,
  }) => {
    const { dialog, footer } = await openModal(page, "Seat Available Demo");

    const enroll = footer.getByRole("button", { name: "Enroll", exact: true });
    await expect(enroll).toBeVisible();
    await expect(dialog.getByText("You're enrolled")).toHaveCount(0);

    // Room left, so nothing is handed over — this must act without asking.
    let asked = false;
    page.once("dialog", (confirmation) => {
      asked = true;
      return confirmation.accept();
    });
    await enroll.click();

    await expect(footer.getByText("You're enrolled")).toBeVisible();
    await expect(footer.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
    expect(asked).toBe(false);
  });

  test("a full session offers the waiting list instead", async ({ page }) => {
    const { dialog, footer } = await openModal(page, "Waiting List Only Demo");

    const join = footer.getByRole("button", { name: "Join waiting list" });
    await expect(join).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);

    await join.click();

    await expect(footer.getByText("On the waiting list")).toBeVisible();
    await expect(footer.getByRole("button", { name: "Leave", exact: true })).toBeVisible();
    const roster = capacity(dialog);
    await expect(roster).toContainText("1/1");
    await expect(roster).toContainText("1 waiting");
  });

  test("a full session keeps your waiting-list place when leaving never reaches the server", async ({
    page,
  }) => {
    const { dialog, footer } = await openModal(page, "Waiting List Only Demo");
    await footer.getByRole("button", { name: "Join waiting list" }).click();
    await expect(footer.getByRole("button", { name: "Leave", exact: true })).toBeVisible();
    const roster = capacity(dialog);
    await page.route(ENROLL_POST, (route) =>
      route.request().method() === "POST" ? route.abort() : route.fallback(),
    );
    page.on("dialog", (confirmation) => confirmation.accept());

    const aborted = page.waitForEvent("requestfailed");
    await footer.getByRole("button", { name: "Leave", exact: true }).click();
    await aborted;

    // Still waiting: the optimistic leave rolled back.
    await expect(roster).toContainText("1/1");
    await expect(roster).toContainText("1 waiting");
    await expect(footer.getByText("On the waiting list")).toBeVisible();
  });
});

test.describe("The seat stack answers an Enroll click at once", () => {
  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await release(page, "Seat Available Demo");
  });

  test("lists you before the server answers, and keeps you once it does", async ({ page }) => {
    const { dialog, footer } = await openModal(page, "Seat Available Demo");
    let answer = (): void => {};
    const held = new Promise<void>((resolve) => {
      answer = resolve;
    });
    await page.route(ENROLL_POST, async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      await held;
      return route.continue();
    });
    const roster = capacity(dialog);
    await expect(roster).toContainText("0/5");

    await footer.getByRole("button", { name: "Enroll", exact: true }).click();

    // The request is still held here: only the client can have done this.
    await expect(roster).toContainText("1/5");
    await expect(dialog.getByRole("img", { name: "E2E Tester" })).toBeVisible();
    await expect(footer.getByText("You're enrolled")).toHaveCount(0);

    answer();

    await expect(footer.getByText("You're enrolled")).toBeVisible();
    await expect(roster).toContainText("1/5");
    await expect(dialog.getByRole("img", { name: "E2E Tester" })).toBeVisible();
  });

  test("takes you back out when the enroll never reaches the server", async ({ page }) => {
    const { dialog, footer } = await openModal(page, "Seat Available Demo");
    await page.route(ENROLL_POST, (route) =>
      route.request().method() === "POST" ? route.abort() : route.fallback(),
    );
    const roster = capacity(dialog);

    await footer.getByRole("button", { name: "Enroll", exact: true }).click();

    await expect(roster).toContainText("0/5");
    await expect(dialog.getByRole("img", { name: "E2E Tester" })).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Enroll", exact: true })).toBeVisible();
  });

  test("takes you back out when the answer replaces the footer without a roster update", async ({
    page,
  }) => {
    const { dialog, footer } = await openModal(page, "Seat Available Demo");
    // Stands in for any answer the enroll view did not word, such as a
    // redirect htmx follows: it swaps the form away and says nothing of the
    // roster.
    await page.route(ENROLL_POST, (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 200, contentType: "text/html", body: "<div></div>" })
        : route.fallback(),
    );
    const roster = capacity(dialog);

    const answered = page.waitForResponse((response) => response.request().method() === "POST");
    await footer.getByRole("button", { name: "Enroll", exact: true }).click();
    await answered;

    await expect(roster).toContainText("0/5");
    await expect(dialog.getByRole("img", { name: "E2E Tester" })).toHaveCount(0);
  });
});
