import { expect, test } from "@playwright/test";

import { analyzePageAccessibility } from "./helpers/a11y";

// The seeded e2e-tester has one unread WAITLIST_PROMOTED notification
// (tests/e2e/scripts/bootstrap_data.py), so the navbar dropdown has content.

test.describe("Navbar notifications dropdown", () => {
  test("unread count is in the accessible name, not colour alone", async ({ page }) => {
    await page.goto("/events/");

    await expect(page.getByRole("button", { name: /Notifications \(1 unread\)/ })).toBeVisible();
  });

  test("is keyboard operable with a live aria-expanded", async ({ page }) => {
    await page.goto("/events/");

    const trigger = page.getByRole("button", { name: /Notifications/ });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    await trigger.focus();
    await page.keyboard.press("Enter");

    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const item = page.getByRole("link", { name: /a spot opened in/i });
    await expect(item).toBeVisible();

    await page.screenshot({
      path: "test-results/notifications-dropdown-open.png",
    });

    await page.keyboard.press("Escape");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(item).toBeHidden();
  });

  test("open dropdown has no critical or serious axe violations", async ({ page }) => {
    await page.goto("/events/");

    await page.getByRole("button", { name: /Notifications/ }).click();
    await expect(page.getByRole("link", { name: /a spot opened in/i })).toBeVisible();

    await analyzePageAccessibility(page, { include: "nav" });
  });
});

test.describe("Navbar profile menu (a11y upgrade)", () => {
  test("opens on hover, preserves the safe path, and closes on pointer out", async ({ page }) => {
    await page.goto("/events/");

    const trigger = page.getByRole("button", { name: /Account menu/ });
    const panel = page.locator("#navbar-profile-panel");
    const surface = panel.locator("[data-menu-surface]");

    await expect
      .poll(() => surface.evaluate((element) => Number.parseFloat(getComputedStyle(element).scale)))
      .toBeCloseTo(0.98);
    await expect(surface).toHaveCSS("filter", "blur(1px)");

    await trigger.hover();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(surface).toHaveCSS("transition-duration", "0.21s");
    await expect
      .poll(() => surface.evaluate((element) => Number.parseFloat(getComputedStyle(element).scale)))
      .toBeCloseTo(1);
    await expect(surface).toHaveCSS("filter", "none");

    const transformOrigin = await surface.evaluate((element) => {
      const [x, y] = getComputedStyle(element).transformOrigin.split(" ").map(Number.parseFloat);
      return { x, y, width: element.offsetWidth };
    });
    expect(transformOrigin.x).toBeCloseTo(transformOrigin.width);
    expect(transformOrigin.y).toBe(0);

    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(surface).toHaveCSS("transition-duration", "0.16s");
    await expect(panel).toBeHidden();

    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    const triggerBox = await trigger.boundingBox();
    const panelBox = await panel.boundingBox();
    if (!triggerBox || !panelBox) throw new Error("Profile menu is not laid out");

    await page.mouse.move(triggerBox.x + triggerBox.width / 2, triggerBox.y + triggerBox.height);
    await page.mouse.move(panelBox.x + panelBox.width - 4, panelBox.y - 4);
    await page.mouse.move(panelBox.x + panelBox.width - 4, panelBox.y + 4);

    await expect(trigger).toHaveAttribute("aria-expanded", "true");

    await page.mouse.move(panelBox.x - 20, panelBox.y + 20);
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("is keyboard operable with a live aria-expanded", async ({ page }) => {
    await page.goto("/events/");

    const trigger = page.getByRole("button", { name: /Account menu/ });
    await expect(trigger).toHaveAttribute("aria-expanded", "false");

    await trigger.focus();
    await page.keyboard.press("Enter");

    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const logout = page.getByRole("link", { name: /Log out/ });
    await expect(logout).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(logout).toBeHidden();
  });

  test("open menu has no critical or serious axe violations", async ({ page }) => {
    await page.goto("/events/");

    await page.getByRole("button", { name: /Account menu/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: /Log out/ })).toBeVisible();

    await analyzePageAccessibility(page, { include: "nav" });
  });
});
