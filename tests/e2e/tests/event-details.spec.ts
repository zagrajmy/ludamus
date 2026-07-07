import type { Page } from "@playwright/test";

import { expect, test } from "@playwright/test";

import { createIosModalContext } from "./helpers/ios-modal";

const settleViewTransitions = (page: Page): Promise<void> =>
  page
    .waitForFunction(
      () =>
        !document
          .getAnimations()
          .some((a) =>
            (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith("::view-transition"),
          ),
    )
    .then(() => undefined);

test.describe("Event detail page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/autumn-open/");
  });

  test("shows event information and enrollment status pill", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Autumn Open Playtest" })).toBeVisible();

    await expect(page.getByText("Enrollment Open")).toBeVisible();
    await expect(page.getByText("Proposals Open")).toBeVisible();
    await expect(page.getByText("Upcoming")).toHaveCount(0);
  });

  test("renders session cards with locations and opens detail modal", async ({ page }) => {
    const sessionCards = page.getByRole("article");
    await expect(sessionCards).toHaveCount(3);

    const megaStrategyCard = sessionCards.filter({
      hasText: "Mega Strategy Lab",
    });
    await expect(megaStrategyCard).toContainText("Convention Center");
    await expect(megaStrategyCard).toContainText("Main Hall");
    await expect(megaStrategyCard).toContainText("East Wing");

    await megaStrategyCard
      .getByRole("link", { name: "Open details for Mega Strategy Lab" })
      .click();

    const detailDialog = page.getByRole("dialog", {
      name: "Mega Strategy Lab",
    });
    await expect(detailDialog).toBeVisible();
    await expect(detailDialog).toContainText("Alex Morgan");

    await detailDialog.getByRole("button", { name: "Close" }).click();
    await expect(detailDialog).toBeHidden();
  });

  test("opening session modal does not log Transition was skipped", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).click();

    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);

    expect(pageErrors.filter((message) => message.includes("Transition was skipped"))).toEqual([]);
  });

  test("session card shows a slot while its modal is open", async ({ page }) => {
    const card = page.locator('.session-card[data-session-id="2"]');
    const title = card.getByRole("heading", { name: "Mega Strategy Lab" });

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).click();

    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);
    await expect(card).toHaveClass(/session-card-suppressed/);
    await expect(card).toBeVisible();
    await expect(title).toBeHidden();

    await page.getByRole("button", { name: "Close" }).click();
    await settleViewTransitions(page);
    await expect(title).toBeVisible();
    await expect(card).not.toHaveClass(/session-card-suppressed/);
  });

  test("mobile session modal closes on iOS tap (touchmove not cancelled)", async ({
    browser,
    browserName,
  }) => {
    test.skip(browserName === "firefox", "Firefox does not support mobile emulation");
    const context = await createIosModalContext(browser, browserName);
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    await page.getByRole("link", { name: "Open details for Cozy Storytellers Circle" }).click();

    const detailDialog = page.getByRole("dialog", {
      name: "Cozy Storytellers Circle",
    });
    await expect(detailDialog).toBeVisible();
    await settleViewTransitions(page);

    const closeButton = detailDialog.getByRole("button", { name: "Close" });
    await expect(closeButton).toBeInViewport();

    const pageScrollLocked = await page.evaluate(() => {
      const bodyOverflow = getComputedStyle(document.body).overflowY;
      const bodyPosition = getComputedStyle(document.body).position;
      return bodyOverflow === "hidden" || bodyPosition === "fixed";
    });
    expect(pageScrollLocked).toBe(true);

    const closeTouchMoveAllowed = await closeButton.evaluate((close) => {
      const move = new Event("touchmove", { bubbles: true, cancelable: true });
      Object.defineProperties(move, {
        targetTouches: { value: [{ clientY: 200 }] },
        touches: { value: [{ clientY: 200 }] },
      });

      close.dispatchEvent(move);
      return !move.defaultPrevented;
    });
    expect(closeTouchMoveAllowed).toBe(true);

    await closeButton.click();
    await expect(detailDialog).toBeHidden();
    await context.close();
  });

  test("mobile session modal opened over a scrolled page keeps the Close button tappable on iOS", async ({
    browser,
    browserName,
  }) => {
    test.skip(browserName === "firefox", "Firefox does not support mobile emulation");
    const context = await createIosModalContext(browser, browserName);
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");

    const scrolledTop = await page.evaluate(() => {
      const root = document.getElementById("app-scroll");
      if (!root) return -1;
      const spacer = document.createElement("div");
      spacer.style.height = "1500px";
      spacer.style.flexShrink = "0";
      root.appendChild(spacer);
      root.scrollTop = 1000;
      const top = root.scrollTop;
      document
        .querySelector<HTMLAnchorElement>(
          'a[aria-label="Open details for Cozy Storytellers Circle"]',
        )
        ?.click();
      return top;
    });
    expect(scrolledTop).toBeGreaterThan(0);

    const detailDialog = page.getByRole("dialog", {
      name: "Cozy Storytellers Circle",
    });
    await expect(detailDialog).toBeVisible();
    await settleViewTransitions(page);

    const locked = await page.evaluate(() => {
      const root = document.getElementById("app-scroll");
      return {
        overflowY: root ? getComputedStyle(root).overflowY : "",
        documentScrollY: window.scrollY,
        bodyPosition: getComputedStyle(document.body).position,
      };
    });
    expect(locked.overflowY).toBe("hidden");
    expect(locked.documentScrollY).toBe(0);
    expect(locked.bodyPosition).not.toBe("fixed");

    const closeButton = detailDialog.getByRole("button", { name: "Close" });
    await expect(closeButton).toBeInViewport();
    await expect
      .poll(() =>
        closeButton.evaluate((close) => {
          const r = close.getBoundingClientRect();
          const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return !!(hit && hit.closest("[data-modal-close]"));
        }),
      )
      .toBe(true);

    await closeButton.click();
    await expect(detailDialog).toBeHidden();
    await settleViewTransitions(page);
    await expect
      .poll(() =>
        page.evaluate(() => {
          const root = document.getElementById("app-scroll");
          return root ? root.scrollTop : -1;
        }),
      )
      .toBe(scrolledTop);
    const overflowAfter = await page.evaluate(() => {
      const root = document.getElementById("app-scroll");
      return root ? getComputedStyle(root).overflowY : "";
    });
    expect(overflowAfter).not.toBe("hidden");

    await context.close();
  });

  test("allows iOS touch scrolling inside long mobile session modal content", async ({
    browser,
    browserName,
  }) => {
    test.skip(browserName === "firefox", "Firefox does not support mobile emulation");
    const context = await createIosModalContext(browser, browserName);
    await context.addInitScript(() => {
      Object.defineProperty(window.navigator, "platform", {
        get: () => "iPhone",
      });
      Object.defineProperty(window.navigator, "maxTouchPoints", {
        get: () => 1,
      });
    });
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    const controls = await page
      .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
      .getAttribute("aria-controls");
    const sessionId = controls?.replace("session-", "");
    expect(sessionId).toBeTruthy();

    await page.evaluate((id) => {
      const description = document.querySelector(
        `#session-${id} [id^="info-"] [data-morph="desc"]`,
      );
      if (!description) throw new Error("Missing session description");
      description.innerHTML = Array.from(
        { length: 28 },
        (_, index) => `<p>Long mobile session description paragraph ${index + 1}.</p>`,
      ).join("");
    }, sessionId);

    await page.getByRole("link", { name: "Open details for Cozy Storytellers Circle" }).click();
    const detailDialog = page.getByRole("dialog", {
      name: "Cozy Storytellers Circle",
    });
    await expect(detailDialog).toBeVisible();

    const mobileModalLayout = await page.evaluate(() => {
      const dialog = document.querySelector("dialog[open]");
      const tabContent = dialog?.querySelector('[role="tabpanel"]')?.parentElement;
      if (!(dialog instanceof HTMLElement) || !(tabContent instanceof HTMLElement)) return null;

      const dialogBox = dialog.getBoundingClientRect();
      const tabContentBox = tabContent.getBoundingClientRect();
      return {
        dialogHeight: dialogBox.height,
        tabContentHeight: tabContentBox.height,
        viewportHeight: window.innerHeight,
      };
    });
    expect(mobileModalLayout).not.toBeNull();
    if (mobileModalLayout === null) {
      throw new Error("Mobile modal layout metrics were unavailable");
    }
    expect(mobileModalLayout.dialogHeight).toBeGreaterThan(mobileModalLayout.viewportHeight * 0.75);
    expect(mobileModalLayout.tabContentHeight).toBeGreaterThan(240);

    const touchMoveAllowed = await page.evaluate(() => {
      const dialog = document.querySelector("dialog[open]");
      const activePanel = dialog?.querySelector('[role="tabpanel"][data-active]');
      const text = activePanel?.querySelector("p");
      if (!dialog || !(activePanel instanceof HTMLElement) || !text) return false;

      const start = new Event("touchstart", {
        bubbles: true,
        cancelable: true,
      });
      Object.defineProperties(start, {
        targetTouches: { value: [{ clientY: 300 }] },
        touches: { value: [{ clientY: 300 }] },
      });
      const move = new Event("touchmove", { bubbles: true, cancelable: true });
      Object.defineProperties(move, {
        targetTouches: { value: [{ clientY: 200 }] },
        touches: { value: [{ clientY: 200 }] },
      });

      text.dispatchEvent(start);
      text.dispatchEvent(move);

      return activePanel.scrollHeight > activePanel.clientHeight && !move.defaultPrevented;
    });
    expect(touchMoveAllowed).toBe(true);

    await detailDialog.getByRole("button", { name: "Close" }).click();
    await expect(detailDialog).toBeHidden();
    await context.close();
  });
});

test.describe("Anonymous code modal", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/autumn-open/anonymous/do/activate");
    await expect(page.getByRole("heading", { name: "Anonymous Mode Active" })).toBeVisible();
  });

  test("opens the code-entry dialog from the banner and cancels back out", async ({ page }) => {
    await page.getByRole("link", { name: /Enter Different Code/ }).click();

    const dialog = page.getByRole("dialog", { name: "Enter Different Code" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Anonymous Code")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Switch to This Code" })).toBeVisible();

    const pageScrollLocked = await page.evaluate(() => {
      const bodyOverflow = getComputedStyle(document.body).overflowY;
      const bodyPosition = getComputedStyle(document.body).position;
      return bodyOverflow === "hidden" || bodyPosition === "fixed";
    });
    expect(pageScrollLocked).toBe(true);

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("closes the code-entry dialog from the X button", async ({ page }) => {
    await page.getByRole("link", { name: /Enter Different Code/ }).click();

    const dialog = page.getByRole("dialog", { name: "Enter Different Code" });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
  });

  test("rejects an unknown code with a flash message and stays on the event", async ({ page }) => {
    await page.getByRole("link", { name: /Enter Different Code/ }).click();
    const dialog = page.getByRole("dialog", { name: "Enter Different Code" });
    await dialog.getByLabel("Anonymous Code").fill("zzzz99");
    await dialog.getByRole("button", { name: "Switch to This Code" }).click();

    await expect(page).toHaveURL(/\/event\/autumn-open/);
    await expect(page.getByText(/Invalid code/i)).toBeVisible();
  });
});
