import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const auroraName = "Aurora Convention Hall";
const glacierName = "Glacier Amphitheatre";

function venueNode(page: Page, name: string) {
  return page.getByRole("listitem").filter({
    has: page.getByText(name, { exact: true }),
  });
}

function disclosureHandle(page: Page, name: string) {
  return venueNode(page, auroraName).getByRole("button", {
    name: `Reorder or toggle ${name} — arrow keys reorder; Enter or Space toggles children`,
    exact: true,
  });
}

function dragHandle(page: Page, name: string) {
  return venueNode(page, auroraName).getByRole("button", {
    name: new RegExp(`^Reorder(?: or toggle)? ${name} —`),
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

  test("the branch border and drag handle fold only their own children", async ({ page }) => {
    const aurora = venueNode(page, auroraName);
    const auroraToggle = disclosureHandle(page, auroraName);
    const northToggle = disclosureHandle(page, "North Wing");
    const gallery = aurora.getByText("Frost Gallery", { exact: true });
    const lounge = aurora.getByText("Hearth Lounge", { exact: true });

    await expect(page.getByRole("button", { name: /^Toggle children of/ })).toHaveCount(0);
    await expect(auroraToggle).toHaveAttribute("aria-expanded", "true");
    await expect(gallery).toBeVisible();
    const northChildrenId = await northToggle.getAttribute("aria-controls");
    expect(northChildrenId).not.toBeNull();
    await page.locator(`#${northChildrenId}`).click({ position: { x: 2, y: 2 } });
    await expect(northToggle).toHaveAttribute("aria-expanded", "false");
    await expect(gallery).toBeHidden();
    await expect(lounge).toBeVisible();

    await auroraToggle.click();
    await expect(auroraToggle).toHaveAttribute("aria-expanded", "false");
    await expect(lounge).toBeHidden();
    await expect(page.getByText(auroraName, { exact: true })).toBeVisible();
    await expect(
      venueNode(page, glacierName).getByText(glacierName, { exact: true }),
    ).toBeVisible();
    await expect(auroraToggle).toBeFocused();

    await auroraToggle.click();
    await expect(lounge).toBeVisible();
    await expect(gallery).toBeHidden();
    await northToggle.click();
    await expect(gallery).toBeVisible();
  });

  test("Enter and Space toggle children without changing sibling order", async ({ page }) => {
    const toggle = disclosureHandle(page, auroraName);
    const aurora = venueNode(page, auroraName);
    const galleryLink = aurora.getByRole("link", { name: "Edit Frost Gallery", exact: true });
    const orderBefore = await aurora.getByRole("listitem").allTextContents();
    await expect(toggle).toHaveAttribute("aria-controls", /.+/);
    expect(
      await toggle.evaluate(
        (button) => document.getElementById(button.getAttribute("aria-controls") ?? "")?.tagName,
      ),
    ).toBe("UL");

    await toggle.focus();
    await toggle.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(galleryLink).toBeHidden();
    await toggle.press("Space");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(galleryLink).toBeVisible();
    expect(await aurora.getByRole("listitem").allTextContents()).toEqual(orderBefore);
  });

  test("leaf drag handles and secondary clicks do not collapse the tree", async ({ page }) => {
    const toggle = disclosureHandle(page, auroraName);
    await toggle.click({ button: "right" });
    await page.keyboard.press("Escape");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const leafHandle = page.getByRole("button", {
      name: `Reorder ${glacierName} — use the arrow keys`,
      exact: true,
    });
    await expect(leafHandle).toHaveAttribute("draggable", "true");
    await expect(leafHandle).not.toHaveAttribute("aria-expanded");
    await expect(leafHandle).not.toHaveAttribute("aria-controls");
    await leafHandle.click();
    await expect(
      venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
    ).toBeVisible();
  });

  for (const interaction of ["keyboard", "drag"] as const) {
    test(`${interaction} moves a nested venue to the top level`, async ({ page }) => {
      let movedSpaceId: number | undefined;
      let siblingReorders = 0;
      await page.route("**/venues/do/reorder", async (route) => {
        siblingReorders += 1;
        await route.fulfill({ json: { success: true } });
      });
      await page.route("**/venues/do/move-to-root", async (route) => {
        movedSpaceId = (await route.request().postDataJSON()).space_id;
        await route.fulfill({ json: { success: true } });
      });
      const handle = dragHandle(page, "North Wing");

      if (interaction === "keyboard") {
        await handle.focus();
        await handle.press("ArrowLeft");
      } else {
        await handle.dragTo(
          page.getByText(
            "Drop a nested space here to move it to the top level. Keyboard: focus its handle and press Left Arrow.",
            { exact: true },
          ),
        );
      }

      await expect.poll(() => movedSpaceId).toBeGreaterThan(0);
      expect(siblingReorders).toBe(0);
    });

    test(`${interaction} reorders a collapsed venue without toggling it`, async ({ page }) => {
      // NOTE: endpoint persistence is covered in panel.spec.ts; keep this gesture check from mutating shared fixtures.
      await page.route("**/venues/do/reorder", (route) =>
        route.fulfill({ json: { success: true } }),
      );
      const toggle = disclosureHandle(page, "North Wing");
      const handle = dragHandle(page, "North Wing");
      const siblingNames = venueNode(page, auroraName).getByText(/^(Hearth Lounge|North Wing)$/);
      const originalOrder = await siblingNames.allTextContents();
      const from = originalOrder.indexOf("North Wing");
      const to = from === 0 ? 1 : from - 1;
      const reordered = [...originalOrder];
      reordered.splice(to, 0, ...reordered.splice(from, 1));

      await toggle.click();
      const response = savedOrder(page);
      if (interaction === "keyboard") {
        await handle.press(from === 0 ? "ArrowDown" : "ArrowUp");
        await expect(handle).toBeFocused();
      } else {
        const target = dragHandle(page, originalOrder[to]);
        const targetBox = await target.boundingBox();
        expect(targetBox).not.toBeNull();
        await handle.dragTo(target, {
          targetPosition: {
            x: (targetBox?.width ?? 0) / 2,
            y: ((targetBox?.height ?? 0) * (from === 0 ? 3 : 1)) / 4,
          },
        });
      }
      await response;
      expect(await siblingNames.allTextContents()).toEqual(reordered);
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(
        venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
      ).toBeHidden();
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(
        venueNode(page, auroraName).getByText("Frost Gallery", { exact: true }),
      ).toBeVisible();
    });
  }
});
