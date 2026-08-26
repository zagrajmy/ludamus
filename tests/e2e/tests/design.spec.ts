import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

test.describe("Design system page", () => {
  /** The upgraded combobox input — waits out the enhancement, which a native
   * <select> would otherwise satisfy, since it carries the combobox role too. */
  const upgradedCombobox = async (page: Page, name: string) => {
    const combobox = page.getByRole("combobox", { name });
    await expect(combobox).toHaveAttribute("aria-autocomplete", "list");
    return combobox;
  };

  test("renders design showcase with component sections", async ({ page }) => {
    await page.goto("/design/");

    // Page should load (design.html extends base)
    await expect(page).toHaveTitle(/tessera/i);

    // Should contain component examples — buttons, cards, alerts, etc.
    await expect(page.getByRole("button").first()).toBeVisible();

    await page.screenshot({
      path: "test-results/design-page.png",
      fullPage: true,
    });
  });

  test("lets people exercise toast stacking and dismissal", async ({ page }) => {
    await page.goto("/design/");

    const playground = page.getByRole("group", { name: "Toast playground" });
    await playground.getByRole("button", { name: "Show success" }).click();
    await playground.getByRole("button", { name: "Show sticky error" }).click();

    const toasts = page.getByRole("region", { name: "Notifications" }).locator("[data-flash]");
    await expect(toasts).toHaveCount(2);
    await expect(toasts.first()).toHaveAttribute("data-flash-mounted", "true");
    await expect
      .poll(() =>
        toasts.evaluateAll((elements) => {
          const [front, back] = elements.map((element) => element.getBoundingClientRect());
          return back.top - front.top < front.height;
        }),
      )
      .toBe(true);

    await playground.getByRole("button", { name: "Dismiss all" }).click();
    await expect(toasts).toHaveCount(0);
  });

  test("upgrades the combobox and filters its options", async ({ page }) => {
    await page.goto("/design/");

    const combobox = await upgradedCombobox(page, "Fruit");
    // The upgrade swaps the control: the select steps aside for the input.
    await expect(page.locator("#t-combobox")).toBeHidden();

    await combobox.fill("ap");
    await expect(page.getByRole("listbox", { name: "Fruit" }).getByRole("option")).toHaveText([
      "Apple",
      "Apricot",
    ]);

    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    await combobox.press("Enter");
    await expect(combobox).toHaveValue("Apricot");
    // The select is still the value — a form would post this.
    await expect(page.locator("#t-combobox")).toHaveValue("apricot");
  });

  test("keeps the native select when scripts do not run", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto("/design/");

    // The <noscript> content becomes real elements again exactly here, which
    // is the whole point of putting the select in one: scriptless it is the
    // working control, and with scripts it costs the page no nodes at all.
    await expect(page.locator("select#t-combobox")).toBeVisible();
    await expect(page.locator("#t-combobox-input")).toBeHidden();

    await context.close();
  });

  test("follows the combobox keyboard contract", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    const value = page.locator("#t-combobox");

    // Alt+Down opens without moving the active option, per the pattern.
    await combobox.focus();
    await combobox.press("Alt+ArrowDown");
    await expect(combobox).toHaveAttribute("aria-expanded", "true");
    await expect(combobox).not.toHaveAttribute("aria-activedescendant", /./);

    // Up from there wraps to the last option rather than clamping.
    await combobox.press("ArrowUp");
    await expect(page.getByRole("option", { name: "Cherry" })).toHaveAttribute("data-active", "");

    // Alt+Up commits the active option and closes.
    await combobox.press("Alt+ArrowUp");
    await expect(value).toHaveValue("cherry");
    await expect(combobox).toHaveAttribute("aria-expanded", "false");

    // Tab commits the active option on the way out.
    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    await combobox.press("Tab");
    await expect(value).toHaveValue("apple");
    await expect(combobox).toHaveAttribute("aria-expanded", "false");
  });

  test("navigating the list does not change the value until it is committed", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    const value = page.locator("#t-combobox");

    await combobox.click();
    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    // Moving the active option is not a pick — the select still holds nothing.
    await expect(value).toHaveValue("");

    await combobox.press("Escape");
    await expect(value).toHaveValue("");
  });

  test("keeps the list inside the part of the screen a keyboard leaves", async ({ browser }) => {
    // What a keyboard leaves of a 700px-tall screen: it shrinks and offsets
    // the visual viewport and leaves the layout viewport — and so
    // window.innerHeight — untouched, which is the case placement must read.
    const KEYBOARD_TOP = 180;
    const KEYBOARD_HEIGHT = 320;
    const bandBottom = KEYBOARD_TOP + KEYBOARD_HEIGHT;

    const context = await browser.newContext({
      viewport: { width: 390, height: 700 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    await combobox.scrollIntoViewIfNeeded();
    await combobox.click();

    const list = page.getByRole("listbox", { name: "Fruit" });
    const before = await list.boundingBox();
    // Without this the test could pass on a list that never needed moving —
    // and would quietly go vacuous the day the page's layout shifts.
    expect(before!.y + before!.height).toBeGreaterThan(bandBottom);

    const innerHeight = await page.evaluate(
      ({ height, top }) => {
        const viewport = window.visualViewport!;
        Object.defineProperty(viewport, "height", { configurable: true, value: height });
        Object.defineProperty(viewport, "offsetTop", { configurable: true, value: top });
        viewport.dispatchEvent(new Event("resize"));
        return window.innerHeight;
      },
      { height: KEYBOARD_HEIGHT, top: KEYBOARD_TOP },
    );
    // The layout viewport still claims the room the keyboard took: that gap is
    // the whole bug.
    expect(innerHeight).toBeGreaterThan(bandBottom);

    await expect
      .poll(async () => {
        const box = await list.boundingBox();
        return box ? Math.round(box.y + box.height) : null;
      })
      .toBeLessThanOrEqual(bandBottom + 1);

    const after = await list.boundingBox();
    expect(after!.y).toBeGreaterThanOrEqual(KEYBOARD_TOP - 1);
    // A list squeezed to nothing would satisfy the bounds while being useless.
    expect(after!.height).toBeGreaterThan(80);

    await context.close();
  });

  test("keeps filtering as more characters arrive", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");

    // Clicked first, as a person would: that selects the label already in the
    // box so the typing replaces it.
    await combobox.click();
    // Typed one key at a time: re-showing an already-open popover throws, and
    // the thrown error would take the rest of the keystroke's work with it.
    await combobox.pressSequentially("apr", { delay: 30 });
    // Scoped to this combobox's list: every native <select> on the page
    // contributes options of its own to the accessibility tree.
    const options = page.getByRole("listbox", { name: "Fruit" }).getByRole("option");
    await expect(options).toHaveText(["Apricot"]);
  });

  test("shows the selected option when a query commits nothing", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    const value = page.locator("#t-combobox");

    await combobox.click();
    await page.getByRole("option", { name: "Cherry" }).click();
    await expect(value).toHaveValue("cherry");

    // A query matching nothing, committed with Enter: the box has to fall back
    // to what is actually selected rather than keep the dead query on screen.
    await combobox.fill("zzz");
    await combobox.press("Enter");
    await expect(combobox).toHaveValue("Cherry");
    await expect(value).toHaveValue("cherry");
  });

  test("speaks the result count and marks the active option", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    await combobox.click();

    // aria-selected names the option with virtual focus, not the chosen value:
    // Chrome + VoiceOver stays silent on an activedescendant move otherwise.
    // Opening already activates the selected option, so this steps past it.
    await combobox.press("ArrowDown");
    await expect(page.getByRole("option", { name: "Apple", exact: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("option", { name: "Any fruit" })).toHaveAttribute(
      "aria-selected",
      "false",
    );

    // Left/Right hand the caret back to the text; NVDA goes quiet about
    // editing while an option still holds virtual focus.
    await combobox.press("ArrowRight");
    await expect(combobox).not.toHaveAttribute("aria-activedescendant", /./);

    // The count reaches a live region on the body — one inside the popup is
    // display:none until it opens and announces nothing.
    await combobox.fill("ap");
    await expect(page.getByRole("log")).toHaveText(/Results: 2/, { timeout: 5000 });
    await combobox.fill("zzz");
    await expect(page.getByRole("log")).toContainText("Nothing matches", { timeout: 5000 });
  });

  test("keeps its options out of the page", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");

    // The options a person can pick from are data, not nodes: the <noscript>
    // the server wrote them into holds text and no elements at all.
    expect(
      await page.evaluate(() => {
        const source = document.querySelector("[data-combobox-source]");
        return { elements: source?.children.length, text: (source?.textContent ?? "").length };
      }),
    ).toEqual({ elements: 0, text: expect.any(Number) });

    await combobox.click();
    await expect(page.getByRole("option", { name: "Apple", exact: true })).toBeVisible();
  });

  test("renders a window of rows, not the whole list", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");

    // What a convention actually looks like: hundreds of hosts on a page that
    // already carries a card per session.
    await page.evaluate(() => {
      const options: [string, string][] = Array.from({ length: 400 }, (_, index) => [
        `host-${index}`,
        `Host ${String(index).padStart(3, "0")}`,
      ]);
      document
        .querySelector("#t-combobox")
        ?.closest("[data-combobox]")
        ?.dispatchEvent(new CustomEvent("combobox:sync", { detail: { options } }));
    });
    await combobox.click();

    const listbox = page.getByRole("listbox", { name: "Fruit" });
    const rendered = await listbox.getByRole("option").count();
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(40);

    // The rows nobody can see still have to occupy their scroll height, or the
    // scrollbar would lie about how much list there is.
    const { clientHeight, scrollHeight } = await page.evaluate(() => {
      const scroller = document.querySelector("[data-combobox-scroller]");
      return {
        clientHeight: scroller?.clientHeight ?? 0,
        scrollHeight: scroller?.scrollHeight ?? 0,
      };
    });
    expect(clientHeight).toBeGreaterThan(0);
    expect(scrollHeight).toBeGreaterThan(clientHeight * 5);

    // Every rendered row says where it sits in the list it stands for, since
    // the count a screen reader can see is not the count that matters.
    // 405: the five the page ships plus the four hundred handed over, since a
    // runtime list is appended to the server's rather than replacing it.
    const first = listbox.getByRole("option").first();
    await expect(first).toHaveAttribute("aria-setsize", "405");
    await expect(first).toHaveAttribute("aria-posinset", "1");
  });

  test("shows six rows at a time however tall the viewport is", async ({ page }) => {
    // A tall screen is not an invitation to fill it. The popup used to take
    // whatever room it found, which on a laptop meant a list running the height
    // of the page and burying the schedule behind the control that filters it.
    await page.setViewportSize({ height: 1400, width: 1280 });
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");

    await page.evaluate(() => {
      const options: [string, string][] = Array.from({ length: 400 }, (_, index) => [
        `host-${index}`,
        `Host ${String(index).padStart(3, "0")}`,
      ]);
      document
        .querySelector("#t-combobox")
        ?.closest("[data-combobox]")
        ?.dispatchEvent(new CustomEvent("combobox:sync", { detail: { options } }));
    });
    await combobox.click();

    const { clientHeight, rowHeight } = await page.evaluate(() => {
      const scroller = document.querySelector("[data-combobox-scroller]");
      const row = scroller?.querySelector("[role=option]");
      return {
        clientHeight: scroller?.clientHeight ?? 0,
        rowHeight: row?.getBoundingClientRect().height ?? 0,
      };
    });
    expect(rowHeight).toBeGreaterThan(0);
    // Six rows and the list's own padding — never the seventh.
    expect(clientHeight).toBeLessThan(rowHeight * 7);
    expect(clientHeight).toBeGreaterThanOrEqual(rowHeight * 5);
  });

  test("keeps the active option in the DOM when it arrows past the window", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");

    await page.evaluate(() => {
      const options: [string, string][] = Array.from({ length: 200 }, (_, index) => [
        `host-${index}`,
        `Host ${String(index).padStart(3, "0")}`,
      ]);
      document
        .querySelector("#t-combobox")
        ?.closest("[data-combobox]")
        ?.dispatchEvent(new CustomEvent("combobox:sync", { detail: { options } }));
    });

    // Up from a closed list goes to the last option, which is as far outside
    // the first window as it gets — and aria-activedescendant can only name a
    // node that is actually rendered.
    await combobox.press("ArrowUp");
    const active = await combobox.getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    await expect(page.locator(`#${active}`)).toHaveText(/Host 199/);
    await expect(page.locator(`#${active}`)).toHaveAttribute("aria-selected", "true");

    await combobox.press("Enter");
    await expect(page.locator("#t-combobox")).toHaveValue("host-199");
  });
});
