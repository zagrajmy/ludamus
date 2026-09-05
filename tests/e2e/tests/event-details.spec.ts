import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions } from "./helpers/view-transitions";

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

  test("shows the notice the organizer wrote on the active enrollment window", async ({ page }) => {
    await expect(page.getByText("grab a slot before we fill up!")).toBeVisible();
  });

  test("shows both endpoints of a multi-day event", async ({ page }) => {
    // The seeded event runs 28h, so the header must name the closing day too —
    // start date with start time, end date with end time, each abbreviated to
    // "Fri Sep 4, 16:00" (the English order; the suite runs in English) so the
    // range stays on one line.
    const endpoints = page.locator("[data-event-dates] time");
    const compact = /^[A-Za-z]{3} [A-Za-z]{3} \d{1,2}, \d{1,2}:\d{2}$/;

    await expect(endpoints).toHaveCount(2);
    await expect(endpoints.nth(0)).toHaveText(compact);
    await expect(endpoints.nth(1)).toHaveText(compact);

    // The bug this guards against printed start_time in both halves, which the
    // patterns above cannot tell apart from a correct range.
    const datetimes = await endpoints.evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("datetime")),
    );
    expect(datetimes[0]).not.toBeNull();
    expect(datetimes[1]).not.toBeNull();
    expect(datetimes[0]!.slice(0, 10)).not.toBe(datetimes[1]!.slice(0, 10));
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
      .press("Enter");

    const detailDialog = page.getByRole("dialog", {
      name: "Mega Strategy Lab",
    });
    await expect(detailDialog).toBeVisible();
    await expect(detailDialog).toContainText("Alex Morgan");

    await detailDialog.getByRole("button", { name: "Close" }).click();
    await expect(detailDialog).toBeHidden();
  });

  test("session modal drops the Participants tab when nobody signs up", async ({ page }) => {
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
    const enrollable = page.getByRole("dialog", { name: "Mega Strategy Lab" });
    await expect(enrollable.getByRole("tab", { name: /Participants/ })).toBeVisible();
    await settleViewTransitions(page);
    await enrollable.getByRole("button", { name: "Close" }).click();
    await expect(enrollable).toBeHidden();
    await settleViewTransitions(page);

    // Seeded with no participants limit, so there is no roster to show and the
    // information panel stands alone.
    await page
      .getByRole("link", { name: "Open details for Cozy Storytellers Circle" })
      .press("Enter");
    const dropIn = page.getByRole("dialog", { name: "Cozy Storytellers Circle" });
    await expect(dropIn).toBeVisible();
    await expect(dropIn.getByRole("tab")).toHaveCount(0);
    // The information section drops the tab vocabulary with the bar: a panel
    // announcing itself as a tabpanel with no tab to select it is invalid ARIA.
    await expect(dropIn.getByRole("tabpanel")).toHaveCount(0);
  });

  test("opening session modal does not log Transition was skipped", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);

    expect(pageErrors.filter((message) => message.includes("Transition was skipped"))).toEqual([]);
  });

  test("session card shows a slot while its modal is open", async ({ page }) => {
    const card = page.getByRole("article").filter({ hasText: "Mega Strategy Lab" });
    const sessionSurface = card.locator(":scope > div").first();
    const title = card.getByRole("heading", { name: "Mega Strategy Lab" });

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);
    await expect(sessionSurface).toHaveClass(/session-suppressed/);
    await expect(card).toBeVisible();
    await expect(title).toBeHidden();

    await page.getByRole("button", { name: "Close" }).click();
    await settleViewTransitions(page);
    await expect(title).toBeVisible();
    await expect(card).not.toHaveClass(/session-suppressed/);
  });

  // Whether the morph *feels* right is not assertable; the shape of its groups
  // is. Two invariants matter: the description must NOT be a group — naming it
  // hoists it out unclipped and it spills past the dialog — and the labels the
  // title flies past must come in behind it.
  test("modal chrome morphs on its own groups, staggered behind the title", async ({ page }) => {
    const supportsViewTransitions = await page.evaluate(() => "startViewTransition" in document);
    test.skip(!supportsViewTransitions, "Browser does not implement the View Transition API");

    // Stretch the morph so its animations are readable while it runs.
    await page.addStyleTag({
      content: ":root { --vt-morph-duration: 5s; --vt-morph-exit-duration: 5s; }",
    });
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");

    const pseudoOf = (name: string) => `::view-transition-new(morph-${name})`;
    await page.waitForFunction(
      (pseudo) =>
        document
          .getAnimations()
          .some((a) => (a.effect as KeyframeEffect | null)?.pseudoElement === pseudo),
      pseudoOf("tabs"),
    );

    const delays = await page.evaluate(() => {
      const entries: [string, number][] = [];
      for (const animation of document.getAnimations()) {
        const effect = animation.effect as KeyframeEffect | null;
        const pseudo = effect?.pseudoElement;
        if (effect && pseudo?.startsWith("::view-transition-new(morph-")) {
          entries.push([pseudo, Number(effect.getComputedTiming().delay)]);
        }
      }
      return Object.fromEntries(entries);
    });

    // Naming the description hoists it out of the dialog's snapshot, past the
    // clip that keeps it inside — the bug this guards.
    expect(delays[pseudoOf("desc")]).toBeUndefined();

    // The footer travels with the sheet (see the nesting test below), so it has
    // nothing to wait for; the labels the title flies past do.
    expect(delays[pseudoOf("footer")]).toBe(0);
    expect(delays[pseudoOf("tabs")]).toBeGreaterThan(0);
    expect(delays[pseudoOf("desc-label")]).toBeGreaterThan(delays[pseudoOf("tabs")]);
  });

  // The tab bar exists only in the modal, so it has no old geometry and a
  // new-only group renders at final layout for the whole morph — it would sit
  // there while the sheet is still a fraction of its final width. Nesting puts it
  // under the container's transform and clip.
  test("the modal tab bar morphs nested inside the sheet", async ({ page }) => {
    const supportsNesting = await page.evaluate(() =>
      CSS.supports("view-transition-group", "nearest"),
    );
    test.skip(!supportsNesting, "Browser does not implement view-transition-group");

    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
    await settleViewTransitions(page);

    const groups = await page.evaluate(() =>
      Object.fromEntries(
        [...document.querySelectorAll<HTMLElement>("dialog[open] [data-morph]")].map((element) => [
          element.dataset.morph,
          getComputedStyle(element).getPropertyValue("view-transition-group"),
        ]),
      ),
    );

    expect(groups.tabs).toBe("nearest");
    // Nesting fixes where a group is drawn, not where it starts from. The footer
    // is paired instead (below), and nesting it too would fight that.
    expect(groups.footer).toBe("normal");
    // These have counterparts on the card, so they have to fly free to travel
    // between the two layouts.
    expect(groups.title).toBe("normal");
    expect(groups.host).toBe("normal");
  });

  // Without the card-side anchor the footer is a new-only group, so it starts at
  // its own slot inside the container — for a card in the last column, the far
  // right of the viewport — and slides across. The anchor gives the group an old
  // geometry on the card's bottom edge to grow out of instead.
  test("the modal footer morphs from a zero-height anchor on the card", async ({ page }) => {
    const card = page.getByRole("article").filter({ hasText: "Mega Strategy Lab" });
    const anchor = card.locator('[data-morph="footer"]');

    // It exists only to be captured, so it must not add height to the card.
    expect(await anchor.evaluate((element) => element.getBoundingClientRect().height)).toBe(0);

    const supportsViewTransitions = await page.evaluate(() => "startViewTransition" in document);
    test.skip(!supportsViewTransitions, "Browser does not implement the View Transition API");

    await page.addStyleTag({ content: ":root { --vt-morph-duration: 5s; }" });
    await card.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
    await page.waitForFunction(() =>
      document
        .getAnimations()
        .some((a) =>
          (a.effect as KeyframeEffect | null)?.pseudoElement?.startsWith("::view-transition"),
        ),
    );

    const pseudos = await page.evaluate(() =>
      document
        .getAnimations()
        .map((a) => (a.effect as KeyframeEffect | null)?.pseudoElement)
        .filter((pseudo) => pseudo?.includes("morph-footer")),
    );

    // The discriminator: a group animation exists only when there are two rects
    // to interpolate between. Drop the anchor and this pseudo disappears, leaving
    // just ::view-transition-new — measured both ways.
    expect(pseudos).toContain("::view-transition-group(morph-footer)");
  });

  // Fetched dialogs are cached in the DOM, so without a reset a reopen inherits
  // the last visit's scroll offset — and the morph captures the modal at open,
  // so the card appears to expand into an already-scrolled panel.
  test("reopening a session modal starts at the top of the panel", async ({ page }) => {
    const open = async () => {
      await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
      await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeVisible();
      await settleViewTransitions(page);
    };
    const panel = page.locator("dialog[open] .tab-panel[data-active]");

    await open();
    // The seeded description is short; give the panel something to scroll.
    await page.locator("dialog[open] [data-session-description]").evaluate((element) => {
      element.innerHTML = Array.from(
        { length: 30 },
        (_, index) => `<p>Scrollable paragraph ${index + 1}.</p>`,
      ).join("");
    });
    await panel.evaluate((element) => {
      element.scrollTop = 400;
    });
    await expect.poll(() => panel.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

    await page.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog", { name: "Mega Strategy Lab" })).toBeHidden();
    await settleViewTransitions(page);

    await open();
    await expect.poll(() => panel.evaluate((element) => element.scrollTop)).toBe(0);
    // Without this the assertion above also passes when the reopened panel is
    // simply too short to scroll — i.e. if modals ever stop being cached.
    expect(await panel.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
      true,
    );
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
    const flash = page.getByRole("alert").filter({ hasText: /Invalid code/i });
    await expect(flash).toBeVisible();
    await expect(dialog).toBeVisible();

    const initialMainTop = await page
      .locator("main")
      .evaluate((main) => main.getBoundingClientRect().top);
    expect(
      await page
        .getByRole("region", { name: "Notifications" })
        .evaluate((region) => getComputedStyle(region).position),
    ).toBe("fixed");
    await page.waitForTimeout(300);
    const finalMainTop = await page
      .locator("main")
      .evaluate((main) => main.getBoundingClientRect().top);
    expect(finalMainTop).toBe(initialMainTop);

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
    // ponytail: assert the flash goes away, not how it fades. The 260ms exit
    // transition's intermediate frames aren't observable reliably under CI
    // load (rAF throttling, reduced motion) and two attempts at sampling them
    // both flaked.
    await flash.getByRole("button", { name: "Dismiss" }).click();
    await expect(flash).toHaveCount(0);
  });
});
