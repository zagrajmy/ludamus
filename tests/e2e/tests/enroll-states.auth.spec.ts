import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// enroll-states seeds two sessions on one open window: one with room, one with
// every seat taken (tests/e2e/scripts/bootstrap_data.py). Between them they pin
// both ways *in*, which no other spec exercises from the modal footer.

// The seat badge lives in the footer; the participants tab lists the same
// words for everyone in the session, so badge assertions scope to the footer.
const openModal = async (page: Page, title: string) => {
  await page.goto("/event/enroll-states/");
  await page.getByRole("link", { name: `Open details for ${title}` }).click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return { dialog, footer: dialog.locator("[data-session-footer]") };
};

test.describe("Ways into a session while enrollment is open", () => {
  test("a session with room offers a seat, and taking it flips to the way out", async ({
    page,
  }) => {
    const { footer } = await openModal(page, "Seat Available Demo");

    const enroll = footer.getByRole("button", { name: "Enroll", exact: true });
    await expect(enroll).toBeVisible();
    await expect(footer.getByText("You're enrolled")).toHaveCount(0);

    // Room left, so nothing is handed over — this must act without asking.
    let asked = false;
    page.once("dialog", (confirmation) => {
      asked = true;
      return confirmation.accept();
    });
    await enroll.click();

    await expect(footer.getByText("You're enrolled")).toBeVisible();
    const cancel = footer.getByRole("button", { name: "Cancel", exact: true });
    await expect(cancel).toBeVisible();
    expect(asked).toBe(false);

    // Put the seat back so the spec can run again on the same seeded DB.
    await cancel.click();
    await expect(enroll).toBeVisible();
  });

  test("a full session offers the waiting list instead", async ({ page }) => {
    const { footer } = await openModal(page, "Waiting List Only Demo");

    const join = footer.getByRole("button", { name: "Join waiting list" });
    await expect(join).toBeVisible();
    await expect(footer.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);

    await join.click();

    await expect(footer.getByText("On the waiting list")).toBeVisible();
    const leave = footer.getByRole("button", { name: "Leave", exact: true });
    await expect(leave).toBeVisible();

    await leave.click();
    await expect(join).toBeVisible();
  });
});
