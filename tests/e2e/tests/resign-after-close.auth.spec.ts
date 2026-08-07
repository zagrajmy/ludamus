import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// The seeded e2e-tester holds a confirmed seat on one closed-enrollment session
// and a waiting place on another, both on an event with no enrollment config at
// all (tests/e2e/scripts/bootstrap_data.py). A shut window hides the ways in,
// never the way out.

// The seat badge lives in the footer; the participants tab lists the same words
// for everyone in the session, so badge assertions scope to the footer.
const openModal = async (page: Page, slug: string, title: string) => {
  await page.goto(`/event/${slug}/`);
  await page.getByRole("link", { name: `Open details for ${title}` }).click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return { dialog, footer: dialog.locator("[data-session-footer]") };
};

test.describe("Resigning after enrollment closes", () => {
  test("enrolled viewer can give the seat back", async ({ page }) => {
    const { dialog, footer } = await openModal(page, "closed-enrollment", "Late Resignation Demo");
    await expect(footer.getByText("You're enrolled")).toBeVisible();

    // Closed enrollment makes this one-way, so the button must say so before
    // acting. Capturing the message is the assertion — an absent confirm would
    // leave `confirmed` null and fail below.
    let confirmed: string | null = null;
    page.once("dialog", (confirmation) => {
      confirmed = confirmation.message();
      return confirmation.accept();
    });

    await footer.getByRole("button", { name: "Cancel", exact: true }).click();

    await expect(footer.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
    expect(confirmed).toContain("cannot take it back");

    // The seat is gone for good. Opening the modal put ?session=… in the URL,
    // so a reload lands straight back on it — and it offers no way in.
    await page.reload();
    await expect(dialog).toBeVisible();
    await expect(footer.getByText("You're enrolled")).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Enroll", exact: true })).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Join waiting list" })).toHaveCount(0);
  });

  test("waiting viewer can leave the list", async ({ page }) => {
    const { dialog, footer } = await openModal(page, "closed-enrollment", "Late Waiting List Demo");
    await expect(footer.getByText("On the waiting list")).toBeVisible();

    let confirmed: string | null = null;
    page.once("dialog", (confirmation) => {
      confirmed = confirmation.message();
      return confirmation.accept();
    });

    await footer.getByRole("button", { name: "Leave", exact: true }).click();

    await expect(footer.getByRole("button", { name: "Leave", exact: true })).toHaveCount(0);
    expect(confirmed).toContain("cannot rejoin it");

    await page.reload();
    await expect(dialog).toBeVisible();
    await expect(footer.getByText("On the waiting list")).toHaveCount(0);
    await expect(footer.getByRole("button", { name: "Join waiting list" })).toHaveCount(0);
  });
});

test.describe("A seat on a convention that is over", () => {
  test("states the seat in words, with nothing left to act on", async ({ page }) => {
    const { dialog } = await openModal(page, "past-convention", "Finished Session Demo");

    // The footer badge is gone with the controls, so the info tab carries the
    // state on its own — the only place this sentence is reachable.
    await expect(dialog.getByText("You are enrolled in this session")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
    await expect(dialog.getByText("You're enrolled")).toHaveCount(0);
  });
});
