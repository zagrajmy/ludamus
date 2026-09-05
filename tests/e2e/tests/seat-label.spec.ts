import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Where sign-up is not on offer the label never says "spots left" — that one
// is teal, and an invitation neither state can make. It says one of two muted
// things instead: the cap, or what is free of it once someone holds a seat.
// The two events below are the two ways a reader ends up outside a window: one
// that has shut, and one that has opened for somebody else.
test.describe("The seat label where sign-up is not on offer", () => {
  const row = (page: Page, title: string) => page.locator(".session", { hasText: title }).first();

  test.describe("A window that has shut", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/event/closed-enrollment/");
    });

    // The tester holds one of this session's five seats.
    test("states what is free of the room", async ({ page }) => {
      const seen = row(page, "Late Resignation Demo 1");
      await expect(seen).toContainText("4 free");
      await expect(seen).not.toContainText("spots left");
    });

    test("counts a waiting place as no seat at all", async ({ page }) => {
      await expect(row(page, "Late Waiting List Demo 1")).toContainText("1 seat");
    });
  });

  // A live window seating early-access holders only. It is the one deciding
  // how many seats exist, so the number it halved is what these rows state:
  // five seats at 50% is three, a count neither the room nor the window could
  // have produced alone.
  test.describe("A half-seating window the reader is not in", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/event/early-access/");
    });

    test("states the seats the window leaves, not the room", async ({ page }) => {
      const seen = row(page, "Early Access Demo");
      await expect(seen).toContainText("3 seats");
      await expect(seen).not.toContainText("5 seats");
      await expect(seen).not.toContainText("spots left");
    });

    // Once a seat is gone the cap stops answering "how much room is there", so
    // the row states what is free of it instead — still in the muted type,
    // since who may take one has not changed.
    test("states what is free once a seat is taken", async ({ page }) => {
      const seen = row(page, "Early Access Partly Taken Demo");
      await expect(seen).toContainText("2 free");
      // The cap it would restate if the taken seat went unnoticed. Asserted as
      // the whole label, since a row's description is free to use the word.
      await expect(seen).not.toContainText("3 seats");
      await expect(seen).not.toContainText("spots left");
    });

    test("says nothing is free rather than restating the cap", async ({ page }) => {
      const seen = row(page, "Early Access Nothing Left Demo");
      await expect(seen).toContainText("0 free");
      await expect(seen).not.toContainText("1 seat");
    });
  });
});
