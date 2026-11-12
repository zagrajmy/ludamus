import { type Locator, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";
import { settleViewTransitions } from "./helpers/view-transitions";

// NOTE: bootstrap_data.py seeds one covered and one bare session here, placeholders off.
const EVENT_URL = "/event/session-covers/";
const COVERED = "Meeple Painting";
const BARE = "Blank Canvas";
const LONG_TITLE =
  "Meeple Painting for Beginners: Base Coats, Washes, Highlights and a Two-Tone Cloak";

const WHITE_COVER = {
  contentType: "image/svg+xml",
  body: '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#ffffff"/></svg>',
};
const BUSY_COVER_PATH = path.join(
  __dirname,
  "..",
  "..",
  "..",
  "src",
  "ludamus",
  "static",
  "placeholder-images",
  "04.webp",
);

const VIEWPORTS = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 664 },
  landscape: { width: 844, height: 390 },
};

const openSession = async (page: Page, title: string) => {
  // NOTE: the card's text sits above its stretched link; Enter reaches the link.
  await page.getByRole("link", { name: `Open details for ${title}` }).press("Enter");
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  await settleViewTransitions(page);
  return dialog;
};

const coverOf = (region: Locator) => region.locator("[data-cover-image]");
const cardOf = (page: Page, title: string) => page.getByRole("article").filter({ hasText: title });

const boxOf = async (locator: Locator) => {
  const box = await locator.boundingBox();
  if (!box) throw new Error("element has no box");
  return box;
};

const coverLoaded = (cover: Locator) =>
  expect
    .poll(() => cover.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);

const titleContrast = async (page: Page, title: Locator) => {
  await title.scrollIntoViewIfNeeded();
  const clip = await title.evaluate((element: HTMLElement) => {
    element.style.color = "transparent";
    element.style.textShadow = "none";
    const range = document.createRange();
    range.selectNodeContents(element);
    const rects = [...range.getClientRects()];
    const left = Math.min(...rects.map((rect) => rect.left));
    const top = Math.min(...rects.map((rect) => rect.top));
    const right = Math.max(...rects.map((rect) => rect.right));
    const bottom = Math.max(...rects.map((rect) => rect.bottom));
    return { x: left, y: top, width: right - left, height: bottom - top, lines: rects.length };
  });
  const png = await page.screenshot({
    clip: { x: clip.x, y: clip.y, width: clip.width, height: clip.height },
  });
  await title.evaluate((element: HTMLElement) => {
    element.style.color = "";
    element.style.textShadow = "";
  });
  const scores = await page.evaluate(
    async (src) => {
      const image = new Image();
      image.src = src;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d")!;
      context.drawImage(image, 0, 0);
      const { data } = context.getImageData(0, 0, image.width, image.height);
      const linear = (value: number) => {
        const v = value / 255;
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      };
      const luminances: number[] = [];
      for (let i = 0; i < data.length; i += 4) {
        luminances.push(
          0.2126 * linear(data[i]) + 0.7152 * linear(data[i + 1]) + 0.0722 * linear(data[i + 2]),
        );
      }
      luminances.sort((a, b) => a - b);
      const againstWhite = (luminance: number) => 1.05 / (luminance + 0.05);
      return {
        worst: againstWhite(luminances[luminances.length - 1]),
        median: againstWhite(luminances[Math.floor(luminances.length / 2)]),
      };
    },
    `data:image/png;base64,${png.toString("base64")}`,
  );
  return {
    lines: clip.lines,
    worst: Math.round(scores.worst * 100) / 100,
    median: Math.round(scores.median * 100) / 100,
  };
};

test.describe("Session modal cover", () => {
  test("prints the title on a covered card in white over the cover", async ({ page }) => {
    await page.goto(EVENT_URL);

    const covered = cardOf(page, COVERED);
    const cover = coverOf(covered);
    await coverLoaded(cover);
    const coverBox = await boxOf(cover);
    const title = covered.getByRole("heading", { name: COVERED });
    const titleBox = await boxOf(title);
    expect(titleBox.y).toBeGreaterThan(coverBox.y);
    expect(titleBox.y + titleBox.height).toBeLessThanOrEqual(coverBox.y + coverBox.height);
    await expect(title).toHaveCSS("color", "rgb(255, 255, 255)");

    const bare = cardOf(page, BARE);
    await expect(coverOf(bare)).toHaveCount(0);
    await expect(bare.getByRole("heading", { name: BARE })).not.toHaveCSS(
      "color",
      "rgb(255, 255, 255)",
    );
  });

  test("opens on the card's cover heading, at the card's title size", async ({
    page,
  }, testInfo) => {
    await page.goto(EVENT_URL);
    const cardTitle = cardOf(page, COVERED).getByRole("heading", { name: COVERED });
    const cardType = await cardTitle.evaluate((element) => {
      const style = getComputedStyle(element);
      return { size: style.fontSize, weight: style.fontWeight };
    });
    const dialog = await openSession(page, COVERED);

    const cover = coverOf(dialog);
    await expect(cover).toBeVisible();
    await expect(cover).toHaveAttribute("alt", "");
    await coverLoaded(cover);

    const dialogBox = await boxOf(dialog);
    const coverBox = await boxOf(cover);
    const title = dialog.getByRole("heading", { name: COVERED });
    const titleBox = await boxOf(title);
    expect(coverBox.width).toBeGreaterThanOrEqual(dialogBox.width - 12);
    expect(coverBox.y - dialogBox.y).toBeLessThanOrEqual(6);
    expect(titleBox.y).toBeGreaterThan(coverBox.y);
    expect(titleBox.y + titleBox.height).toBeLessThanOrEqual(coverBox.y + coverBox.height);
    await expect(title).toHaveCSS("font-size", cardType.size);
    await expect(title).toHaveCSS("font-weight", cardType.weight);
    await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();

    await dialog.getByRole("tab", { name: /Participants/ }).click();
    const roster = dialog.getByRole("tabpanel");
    await expect(roster).toBeVisible();
    expect((await boxOf(roster)).height).toBeGreaterThan(40);
    await dialog.getByRole("tab", { name: /Information/ }).click();

    await attachArtifacts(testInfo, {
      name: "session-modal-cover",
      region: dialog,
      facts: { coverSrc: await cover.getAttribute("src"), dialogBox, coverBox, titleBox },
    });
  });

  test("keeps the modal's parts inside the growing sheet mid-morph", async ({ page }) => {
    await page.goto(EVENT_URL);
    const supportsNesting = await page.evaluate(() =>
      CSS.supports("view-transition-group", "nearest"),
    );
    test.skip(!supportsNesting, "Browser does not implement view-transition-group");

    await page.addStyleTag({
      content: ":root { --vt-morph-duration: 5s; --vt-morph-exit-duration: 5s; }",
    });
    await page.getByRole("link", { name: `Open details for ${COVERED}` }).press("Enter");
    await page.waitForFunction(() =>
      document
        .getAnimations()
        .some(
          (animation) =>
            (animation.effect as KeyframeEffect | null)?.pseudoElement ===
            "::view-transition-group(session-morph)",
        ),
    );

    const midway = await page.evaluate(() => {
      const sheet = getComputedStyle(
        document.documentElement,
        "::view-transition-group(session-morph)",
      );
      const groups = Object.fromEntries(
        [...document.querySelectorAll<HTMLElement>("dialog[open] [data-morph]")].map((element) => [
          element.dataset.morph,
          getComputedStyle(element).getPropertyValue("view-transition-group"),
        ]),
      );
      const names = document
        .getAnimations()
        .map((animation) => (animation.effect as KeyframeEffect | null)?.pseudoElement)
        .filter((pseudo) => pseudo?.startsWith("::view-transition-group("));
      return { overflow: sheet.overflow, radius: sheet.borderTopLeftRadius, groups, names };
    });

    expect(midway.overflow).toBe("clip");
    expect(midway.radius).toBe("16px");
    expect(midway.groups).toMatchObject({
      cover: "nearest",
      close: "nearest",
      tabs: "nearest",
      scrim: "normal",
      "cover-title": "normal",
    });
    expect(midway.names).toEqual(
      expect.arrayContaining([
        "::view-transition-group(morph-cover)",
        "::view-transition-group(morph-scrim)",
        "::view-transition-group(morph-cover-title)",
      ]),
    );
  });

  test("scrolls the cover away under a sticky tab bar on a phone", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.phone);
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, COVERED);

    await dialog.locator("[data-session-description]").evaluate((element) => {
      element.insertAdjacentHTML(
        "beforeend",
        Array.from({ length: 12 }, (_, index) => `<p>Extra paragraph ${index + 1}.</p>`).join(""),
      );
    });
    const scroller = dialog.locator("[data-session-scroll]");
    await scroller.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect(coverOf(dialog)).not.toBeInViewport();
    await expect(dialog.getByText("Extra paragraph 12.")).toBeInViewport();
    const tabsBox = await boxOf(dialog.getByRole("tablist"));
    const scrollerBox = await boxOf(scroller);
    expect(Math.abs(tabsBox.y - scrollerBox.y)).toBeLessThanOrEqual(1);
    await expect(dialog.getByRole("button", { name: "Close" })).toBeInViewport();
  });

  test("keeps the plain header for a session without a cover", async ({ page }) => {
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, BARE);

    await expect(coverOf(dialog)).toHaveCount(0);
    await expect(dialog.locator("[data-session-scroll]")).toHaveCount(0);
    const dialogBox = await boxOf(dialog);
    const titleBox = await boxOf(dialog.getByRole("heading", { name: BARE }));
    const closeBox = await boxOf(dialog.getByRole("button", { name: "Close" }));
    expect(titleBox.y - dialogBox.y).toBeLessThan(40);
    expect(
      Math.abs(titleBox.y + titleBox.height / 2 - (closeBox.y + closeBox.height / 2)),
    ).toBeLessThan(4);
  });

  test("leaves a landscape phone most of the dialog", async ({ page }) => {
    await page.setViewportSize(VIEWPORTS.landscape);
    await page.goto(EVENT_URL);
    const dialog = await openSession(page, COVERED);

    const coverBox = await boxOf(coverOf(dialog));
    const dialogBox = await boxOf(dialog);
    expect(coverBox.height / dialogBox.height).toBeLessThanOrEqual(0.45);
    expect(coverBox.width / coverBox.height).toBeLessThanOrEqual(6.01);

    await dialog.locator("[data-session-scroll]").evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await expect(dialog.getByText("lines up its work and we vote")).toBeInViewport();
  });

  for (const [coverName, cover] of [
    ["very light", async () => WHITE_COVER],
    ["busy", async () => ({ contentType: "image/webp", body: await readFile(BUSY_COVER_PATH) })],
  ] as const) {
    for (const viewport of ["desktop", "phone"] as const) {
      test(`keeps the title legible on a ${coverName} cover (${viewport})`, async ({
        page,
      }, testInfo) => {
        const response = await cover();
        await page.route("**/media/sessions/**", (route) => route.fulfill(response));
        await page.setViewportSize(VIEWPORTS[viewport]);
        const results = [];
        for (const colorScheme of ["light", "dark"] as const) {
          await page.emulateMedia({ colorScheme });
          await page.goto(EVENT_URL);
          const card = cardOf(page, COVERED);
          await coverLoaded(coverOf(card));
          const cardTitle = card.getByRole("heading", { name: COVERED });
          const cardSeeded = await titleContrast(page, cardTitle);
          await cardTitle.evaluate((element, text) => {
            element.textContent = text;
          }, LONG_TITLE);
          const cardLong = await titleContrast(
            page,
            card.getByRole("heading", { name: LONG_TITLE }),
          );

          const dialog = await openSession(page, COVERED);
          await coverLoaded(coverOf(dialog));
          const title = dialog.getByRole("heading", { name: COVERED });
          const seeded = await titleContrast(page, title);
          const open = page.locator("dialog[open]");
          await title.evaluate((element, text) => {
            element.textContent = text;
          }, LONG_TITLE);
          const long = await titleContrast(page, open.getByRole("heading", { name: LONG_TITLE }));
          results.push({
            colorScheme,
            card: { seeded: cardSeeded, long: cardLong },
            modal: { seeded, long },
          });
        }

        const factsPath = testInfo.outputPath(
          `contrast-${coverName.replace(" ", "-")}-${viewport}.json`,
        );
        await writeFile(factsPath, `${JSON.stringify(results, null, 2)}\n`);
        await testInfo.attach(path.basename(factsPath), {
          path: factsPath,
          contentType: "application/json",
        });
        for (const { card, modal } of results) {
          for (const { worst } of [card.seeded, card.long, modal.seeded, modal.long]) {
            expect(worst, JSON.stringify(results)).toBeGreaterThanOrEqual(4.5);
          }
        }
      });
    }
  }
});
