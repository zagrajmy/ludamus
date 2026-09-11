import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

async function logIn(page: Page) {
  await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
}

test.describe("Programme room order", () => {
  test.beforeEach(async ({ page }) => {
    await logIn(page);
    await page.goto("/panel/event/autumn-open/venues/?view=programme");
  });

  test("shows scheduled rooms as one flat order and keeps their full paths", async ({ page }) => {
    await expect(page.getByRole("tab", { name: "Programme order" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const order = page.getByRole("list", { name: "Programme room order" });
    await expect(order.getByRole("listitem")).toHaveCount(2);
    await expect(
      order.getByText("Convention Center > Main Hall > East Wing", { exact: true }),
    ).toBeVisible();
    await expect(
      order.getByText("Convention Center > Lounge > Fireside Alcove", { exact: true }),
    ).toBeVisible();
  });

  for (const interaction of ["keyboard", "drag"] as const) {
    test(`reorders the flat list with ${interaction}`, async ({ page }) => {
      let submittedOrder: number[] = [];
      await page.route("**/venues/do/reorder-programme", async (route) => {
        submittedOrder = (await route.request().postDataJSON()).space_ids;
        await route.fulfill({ json: { success: true } });
      });
      const order = page.getByRole("list", { name: "Programme room order" });
      const handles = order.getByRole("button", {
        name: /Reorder .* in the programme/,
      });
      const before = await order.getByRole("listitem").allTextContents();

      if (interaction === "keyboard") {
        await handles.first().focus();
        await handles.first().press("ArrowDown");
      } else {
        await handles.first().dragTo(handles.nth(1));
      }

      await expect.poll(() => submittedOrder.length).toBe(before.length);
      const after = await order.getByRole("listitem").allTextContents();
      expect(after.slice(0, 2)).toEqual([before[1], before[0]]);
      if (interaction === "keyboard") {
        await expect(handles.nth(1)).toBeFocused();
        await expect(page.getByText("East Wing moved to position 2 of 2.")).toHaveText(
          "East Wing moved to position 2 of 2.",
        );
      }
    });
  }
});

test("renders the longest path at phone and desktop modal widths", async ({ page }) => {
  await logIn(page);
  await page.goto("/panel/event/autumn-open/venues/");

  const phone = page.getByRole("figure").filter({ hasText: "Phone modal · 390 px viewport" });
  const desktop = page.getByRole("figure").filter({ hasText: "Desktop modal · 800 px wide" });
  const phoneFrame = phone.getByRole("group", { name: "Phone modal preview" });
  const desktopFrame = desktop.getByRole("group", { name: "Desktop modal preview" });

  await expect(phone).toBeVisible();
  await expect(desktop).toBeVisible();
  const venueTreeBox = await page.locator("#space-root-list").boundingBox();
  const previewBox = await phone.boundingBox();
  expect(previewBox?.y ?? 0).toBeGreaterThan((venueTreeBox?.y ?? 0) + (venueTreeBox?.height ?? 0));
  expect(Math.round((await phoneFrame.boundingBox())?.width ?? 0)).toBe(382);
  expect(Math.round((await desktopFrame.boundingBox())?.width ?? 0)).toBe(800);

  await expect(phone.getByTitle(/Convention Center/)).toBeVisible();
  await expect(desktop.getByTitle(/Convention Center/)).toBeVisible();
});
