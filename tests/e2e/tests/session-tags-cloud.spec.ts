import { type Locator, type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

const overflowCard = (page: Page) =>
  page.getByRole("article").filter({
    has: page.getByRole("heading", { name: "Overflow Tags (Design Preview)" }),
  });

const plusCount = (page: Page) => overflowCard(page).getByText(/^\+\d+$/);

const opacityOf = (locator: Locator) =>
  locator.evaluate((element) => getComputedStyle(element).opacity);

const SCREENSHOT_CLIP_MIN_WIDTH = 440;

const LONG_TAG = "Vampire: The Masquerade 5th Edition";

const measure = async (tag: Locator, cloud: Locator) => {
  const tagBox = await tag.evaluate((element) => {
    const pill = element.closest("span[title]") ?? element;
    const { width, right } = pill.getBoundingClientRect();
    return { width, right, isTruncated: element.scrollWidth > element.clientWidth + 1 };
  });
  const cloudBox = await cloud.evaluate((element) => {
    const { width, right } = element.getBoundingClientRect();
    return { width, right };
  });
  return {
    tag: { width: tagBox.width, right: tagBox.right },
    cloud: cloudBox,
    isTruncated: tagBox.isTruncated,
  };
};

const clipAround = async (pieces: Locator[], pad: number) => {
  const boxes = [];
  for (const piece of pieces) {
    const box = await piece.boundingBox();
    if (!box) {
      throw new Error("missing bounding box");
    }
    boxes.push(box);
  }
  const left = Math.min(...boxes.map((box) => box.x));
  const top = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.x + box.width));
  const bottom = Math.max(...boxes.map((box) => box.y + box.height));
  return {
    x: Math.floor(Math.max(0, left - pad)),
    y: Math.floor(Math.max(0, top - pad)),
    width: Math.max(SCREENSHOT_CLIP_MIN_WIDTH, Math.ceil(right - left + pad * 2)),
    height: Math.ceil(bottom - top + pad * 2),
  };
};

test.describe("Session tags cloud", () => {
  test("one +N for the whole cloud, age among the chips, hover shows the rest", async ({
    browserName,
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/design/");

    const card = overflowCard(page);
    await expect(
      card.getByRole("heading", { name: "Overflow Tags (Design Preview)" }),
    ).toBeVisible();

    await expect(plusCount(page)).toHaveCount(1);
    await expect(plusCount(page)).toHaveText("+9");

    const age = card.getByText("12+", { exact: true });
    await expect(age).toBeVisible();
    const order = await card.innerText();
    expect(order.indexOf("12+")).toBeGreaterThan(-1);
    expect(order.indexOf("12+")).toBeLessThan(order.indexOf("+9"));

    const tip = card.getByRole("tooltip");
    await expect.poll(() => opacityOf(tip)).toBe("0");

    await plusCount(page).hover();
    await expect.poll(() => opacityOf(tip)).toBe("1");
    await expect(tip.getByText("Blades in the Dark", { exact: true })).toBeVisible();
    await expect(tip.getByText("gambling", { exact: true })).toBeVisible();

    const clipped = await tip.evaluate((el) => {
      const box = el.getBoundingClientRect();
      for (let parent = el.parentElement; parent; parent = parent.parentElement) {
        const { overflow, overflowX, overflowY } = getComputedStyle(parent);
        if ([overflow, overflowX, overflowY].every((value) => value === "visible")) {
          continue;
        }
        const clip = parent.getBoundingClientRect();
        if (
          box.right > clip.right + 0.5 ||
          box.left < clip.left - 0.5 ||
          box.top < clip.top - 0.5 ||
          box.bottom > clip.bottom + 0.5
        ) {
          return true;
        }
      }
      return false;
    });
    expect(clipped).toBe(false);

    if (browserName !== "chromium") {
      return;
    }

    test.info().snapshotSuffix = "";
    await card.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await plusCount(page).hover();
    await expect.poll(() => opacityOf(tip)).toBe("1");
    await expect(page).toHaveScreenshot("session-card-overflow.png", {
      animations: "disabled",
      caret: "hide",
      clip: await clipAround([card, tip], 16),
      maxDiffPixelRatio: 0.05,
    });
  });

  test("a tag wider than 200px spends the card's width, then stops at its edge", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/design/");

    const card = overflowCard(page);
    const cloud = card.locator(".session-tags-cloud");
    const tag = cloud.getByText(LONG_TAG, { exact: true });
    await expect(tag).toBeVisible();

    const wide = await measure(tag, cloud);
    expect(wide.tag.width).toBeGreaterThan(200);
    expect(wide.tag.right).toBeLessThanOrEqual(wide.cloud.right + 0.5);
    expect(wide.isTruncated).toBe(false);

    await page.setViewportSize({ width: 380, height: 900 });
    const narrow = await measure(tag, cloud);
    expect(narrow.cloud.width).toBeLessThan(wide.tag.width);
    expect(narrow.tag.width).toBeCloseTo(narrow.cloud.width, 0);
    expect(narrow.isTruncated).toBe(true);
  });
});
