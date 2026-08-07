import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// enroll-states seeds two sessions on one open window: one with room, one with
// every seat taken (tests/e2e/scripts/bootstrap_data.py). Between them they pin
// both ways *in*, which no other spec exercises from the modal footer.

// The seat badge lives in the footer; the participants tab lists the same words
// for everyone in the session, so badge assertions scope to the footer. Absence
// assertions scope to the dialog, since the footer itself can disappear.
const openModal = async (page: Page, title: string) => {
  await page.goto("/event/enroll-states/");
  await page.getByRole("link", { name: `Open details for ${title}` }).click();
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

test.describe("Ways into a session while enrollment is open", () => {
  test.afterEach(async ({ page }) => {
    await release(page, "Seat Available Demo");
    await release(page, "Waiting List Only Demo");
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
  });
});
