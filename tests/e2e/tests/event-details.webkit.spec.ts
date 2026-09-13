import { expect, test } from "./helpers/fixtures";
import { createIosModalContext } from "./helpers/ios-modal";
import {
  settleViewTransitions,
  supportsViewTransitions,
  trackViewTransitions,
  viewTransitionsStarted,
} from "./helpers/view-transitions";

// Touch and pointer behaviour on a phone-sized WebKit. The engine is the
// subject here — hit regions, touchmove, and what a modal does over a
// scrolled document — none of which needs browser chrome to be real.
test.describe("Event detail page on a phone", () => {
  test("mobile session modal closes on iOS tap (touchmove not cancelled)", async ({
    browser,
    browserName,
  }) => {
    test.skip(browserName === "firefox", "Firefox does not support mobile emulation");
    const context = await createIosModalContext(browser, browserName);
    const page = await context.newPage();

    await page.goto("/event/autumn-open/");
    await page
      .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
      .press("Enter");

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

    // Tapped, not clicked: the bug this guards is iOS hit-testing a tap against
    // the unscrolled document, and click() drives the mouse path instead.
    const box = await closeButton.boundingBox();
    expect(box).not.toBeNull();
    await page.touchscreen.tap(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await expect(detailDialog).toBeHidden();
    await context.close();
  });

  test("closing a session modal on iOS starts no view transition", async ({
    browser,
    browserName,
  }) => {
    test.skip(browserName === "firefox", "Firefox does not support mobile emulation");
    const context = await createIosModalContext(browser, browserName);
    const page = await context.newPage();
    await trackViewTransitions(page);
    await page.goto("/event/autumn-open/");
    // Pinned: without the API the counter could only ever read zero, and the
    // test would pass for the wrong reason.
    expect(await supportsViewTransitions(page)).toBe(true);

    // The toolbar at the top of the screen and a card under it, both in view,
    // as a reader who has just scrolled to the programme has them. Tapped in
    // place, not pressed: focusing a card would scroll it into view and take
    // the toolbar off the screen the tap below needs it on.
    const TOOLBAR_TOP = 80;
    const search = page.locator("#session-filter");
    await page.evaluate((top) => {
      const root = document.getElementById("app-scroll");
      const box = document.getElementById("session-filter");
      if (root && box) root.scrollTop += box.getBoundingClientRect().top - top;
    }, TOOLBAR_TOP);
    await expect(search).toBeInViewport();
    const opener = await page.evaluate(() => {
      const viewport = globalThis.innerHeight;
      for (const link of document.querySelectorAll<HTMLAnchorElement>(
        "a[aria-controls^='session-']",
      )) {
        const box = link.getBoundingClientRect();
        // Clear of the toolbar above and of the cookie strip along the bottom.
        if (box.top < 140 || box.bottom > viewport - 20) continue;
        // A card's selectable text sits over its link with pointer events of
        // its own, so a tap has to land where the link itself is hit.
        const candidates = [
          [box.left + 16, box.top + 12],
          [box.right - 16, box.top + 12],
          [box.left + 16, box.bottom - 12],
          [box.left + box.width / 2, box.top + 12],
        ];
        for (const [x, y] of candidates) {
          const hit = document.elementFromPoint(x, y);
          if (hit === link || link.contains(hit)) {
            return {
              title: (link.getAttribute("aria-label") ?? "").replace("Open details for ", ""),
              x,
              y,
            };
          }
        }
      }
      return null;
    });
    if (!opener) throw new Error("The fixture needs a card in view under the toolbar");
    await page.touchscreen.tap(opener.x, opener.y);
    const dialog = page.getByRole("dialog", { name: opener.title });
    await expect(dialog).toBeVisible();
    // The open morph holds vt-page-live on <html> for its lifetime (modal.ts).
    await expect(page.locator("html")).not.toHaveClass(/vt-page-live/);

    const startedBefore = await viewTransitionsStarted(page);
    const close = await dialog.getByRole("button", { name: "Close" }).boundingBox();
    const searchBox = await search.boundingBox();
    if (!close || !searchBox) throw new Error("The close button and the search box need positions");
    await page.touchscreen.tap(close.x + close.width / 2, close.y + close.height / 2);
    // The very next tap, with nothing awaited in between: on an iPhone the
    // transition's capture alone used to hold this tap for about a second.
    await page.touchscreen.tap(
      searchBox.x + searchBox.width / 2,
      searchBox.y + searchBox.height / 2,
    );
    await expect(search).toBeFocused();
    await expect(dialog).toBeHidden();
    expect(await viewTransitionsStarted(page)).toBe(startedBefore);
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
    // Against the located button, not against [data-modal-close]: the bug is
    // iOS hit-testing this point at the document behind the dialog, and any
    // other close control answering for it would hide exactly that.
    await expect
      .poll(() =>
        closeButton.evaluate((close) => {
          const r = close.getBoundingClientRect();
          const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return !!hit && (hit === close || close.contains(hit));
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

    await page
      .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
      .press("Enter");
    const detailDialog = page.getByRole("dialog", {
      name: "Cozy Storytellers Circle",
    });
    await expect(detailDialog).toBeVisible();

    // The modal is fetched on open (lazy-loaded), so it only exists in the DOM
    // once visible — inject the long description here, not before the click.
    await page.evaluate((id) => {
      const description = document.querySelector(
        `#session-${id} [id^="info-"] [data-session-description]`,
      );
      if (!description) throw new Error("Missing session description");
      description.innerHTML = Array.from(
        { length: 28 },
        (_, index) => `<p>Long mobile session description paragraph ${index + 1}.</p>`,
      ).join("");
    }, sessionId);

    const mobileModalLayout = await page.evaluate(() => {
      const dialog = document.querySelector("dialog[open]");
      // By class, not by role: a drop-in session's modal has no tab bar, so its
      // information panel carries no tabpanel role to find the container by.
      const tabContent = dialog?.querySelector(".tab-content");
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
      const activePanel = dialog?.querySelector(".tab-panel[data-active]");
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
