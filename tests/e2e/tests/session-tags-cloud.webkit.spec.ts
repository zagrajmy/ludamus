import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const overflowCard = (page: Page) =>
  page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Overflow Tags (Design Preview)" }),
  });

// A popover styled from a position-try fallback is where engines diverge:
// WebKit dropped the registered --tw-* defaults Tailwind's border and shadow
// compose from, and Firefox restarted every transition, holding the bubble
// at its first frame. The desktop projects run this too, Firefox included.
test.describe("Session tags popover flipped below its +N", () => {
  test("opens with its border and shadow", async ({ page }, testInfo) => {
    await page.goto("/design/");
    const card = overflowCard(page);
    const plus = card.getByText(/^\+\d+$/);
    const tip = card.getByRole("tooltip");
    const bubble = tip.locator(".session-tags-bubble");

    // Close under the navbar, the +N leaves the bubble no room above it.
    await plus.evaluate((element) => {
      const scroller = document.querySelector("#app-scroll");
      scroller?.scrollBy({ top: element.getBoundingClientRect().top - 90, behavior: "instant" });
    });
    await plus.hover();

    const [plusBox, tipBox] = await Promise.all([plus.boundingBox(), tip.boundingBox()]);
    expect(tipBox?.y).toBeGreaterThan((plusBox?.y ?? 0) + (plusBox?.height ?? 0));

    await expect
      .poll(() => bubble.evaluate((element) => getComputedStyle(element).opacity))
      .toBe("1");
    const look = await bubble.evaluate((element) => {
      const style = getComputedStyle(element);
      return { border: `${style.borderTopWidth} ${style.borderTopStyle}`, shadow: style.boxShadow };
    });
    expect(look.border).toBe("1px solid");
    expect(look.shadow).not.toBe("none");

    await testInfo.attach("flipped-popover", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
  });
});
