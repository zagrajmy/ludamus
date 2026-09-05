import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const auroraName = "Aurora Convention Hall";
const glacierName = "Glacier Amphitheatre";

function venueNode(page: Page, name: string) {
  return page.getByRole("listitem").filter({
    has: page.getByText(name, { exact: true }),
  });
}

function groupHandle(page: Page, name: string) {
  return venueNode(page, auroraName).getByRole("button", {
    name: `Toggle children of ${name} — drag or use arrow keys to reorder`,
    exact: true,
  });
}

function savedOrder(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.url().endsWith("/venues/do/reorder") && response.request().method() === "POST",
    { timeout: 10_000 },
  );
}

test.describe("Venue tree handles", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await page.goto("/panel/event/frostfire-con/venues/");
  });

  test("clicking a handle collapses only its children and preserves nested state", async ({
    page,
  }) => {
    const aurora = venueNode(page, auroraName);
    const handle = groupHandle(page, auroraName);
    const north = groupHandle(page, "North Wing");
    const gallery = aurora.getByText("Frost Gallery", { exact: true });
    const lounge = aurora.getByText("Hearth Lounge", { exact: true });

    await expect(handle).toHaveAttribute("aria-expanded", "true");
    await expect(gallery).toBeVisible();
    await north.click();
    await expect(north).toHaveAttribute("aria-expanded", "false");
    await expect(gallery).toBeHidden();
    await expect(lounge).toBeVisible();

    await handle.click();
    await expect(handle).toHaveAttribute("aria-expanded", "false");
    await expect(lounge).toBeHidden();
    await expect(page.getByText(auroraName, { exact: true })).toBeVisible();
    await expect(page.getByText(glacierName, { exact: true })).toBeVisible();
    await expect(handle).toBeFocused();

    await handle.click();
    await expect(lounge).toBeVisible();
    await expect(gallery).toBeHidden();
    await north.click();
    await expect(gallery).toBeVisible();
  });

  test("Enter and Space toggle children without changing sibling order", async ({ page }) => {
    const handle = groupHandle(page, auroraName);
    const aurora = venueNode(page, auroraName);
    const galleryLink = aurora.getByRole("link", { name: "Edit Frost Gallery", exact: true });
    const orderBefore = await aurora.getByRole("listitem").allTextContents();
    await expect(handle).toHaveAttribute("aria-controls", /.+/);
    expect(
      await handle.evaluate(
        (button) => document.getElementById(button.getAttribute("aria-controls") ?? "")?.tagName,
      ),
    ).toBe("UL");

    await handle.focus();
    await handle.press("Enter");
    await expect(handle).toHaveAttribute("aria-expanded", "false");
    await expect(galleryLink).toBeHidden();
    await handle.press("Space");
    await expect(handle).toHaveAttribute("aria-expanded", "true");
    await expect(galleryLink).toBeVisible();
    expect(await aurora.getByRole("listitem").allTextContents()).toEqual(orderBefore);
  });

  test("leaf handles and secondary clicks do not collapse the tree", async ({ page }) => {
    const handle = groupHandle(page, auroraName);
    await handle.click({ button: "right" });
    await page.keyboard.press("Escape");
    await expect(handle).toHaveAttribute("aria-expanded", "true");
    const leaf = page.getByRole("button", {
      name: `Reorder ${glacierName} — use the arrow keys`,
      exact: true,
    });
    await expect(leaf).not.toHaveAttribute("aria-expanded");
    await expect(leaf).not.toHaveAttribute("aria-controls");
    await leaf.click();
    await expect(
      venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
    ).toBeVisible();
  });

  for (const interaction of ["keyboard", "drag"] as const) {
    test(`${interaction} reorders a collapsed venue without toggling it`, async ({ page }) => {
      // NOTE: endpoint persistence is covered in panel.spec.ts; keep this gesture check from mutating shared fixtures.
      await page.route("**/venues/do/reorder", (route) =>
        route.fulfill({ json: { success: true } }),
      );
      const handle = groupHandle(page, "North Wing");
      const siblingNames = venueNode(page, auroraName).getByText(/^(Hearth Lounge|North Wing)$/);
      const originalOrder = await siblingNames.allTextContents();
      const from = originalOrder.indexOf("North Wing");
      const to = from === 0 ? 1 : from - 1;
      const reordered = [...originalOrder];
      reordered.splice(to, 0, ...reordered.splice(from, 1));

      await handle.click();
      const response = savedOrder(page);
      if (interaction === "keyboard") {
        await handle.press(from === 0 ? "ArrowDown" : "ArrowUp");
        await expect(handle).toBeFocused();
      } else {
        const target = groupHandle(page, originalOrder[to]);
        const targetBox = await target.boundingBox();
        expect(targetBox).not.toBeNull();
        await handle.dragTo(target, {
          targetPosition: { x: 1, y: from === 0 ? (targetBox?.height ?? 1) - 1 : 1 },
        });
      }
      await response;
      expect(await siblingNames.allTextContents()).toEqual(reordered);
      await expect(handle).toHaveAttribute("aria-expanded", "false");
      await expect(
        venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
      ).toBeHidden();
      await handle.click();
      await expect(handle).toHaveAttribute("aria-expanded", "true");
      await expect(
        venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
      ).toBeVisible();
    });
  }
});
