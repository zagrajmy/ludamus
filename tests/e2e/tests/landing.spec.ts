import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

test.describe("Landing", () => {
  test("greets organizers on the root domain and switches to the player view", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle("Zagrajmy • conventions and events");
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeVisible();

    await page.getByText("For players", { exact: true }).filter({ visible: true }).click();

    await expect(page).toHaveURL(/#gracze$/);
    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
    ).toBeVisible();

    await page.getByRole("link", { name: "Browse events" }).first().click();
    await expect(page).toHaveURL(/#g-conventions-heading$/);
    await expect(
      page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
  });

  test("browses the player's conventions without JavaScript", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    try {
      const page = await context.newPage();
      await page.goto("/");
      await page.getByText("For players", { exact: true }).filter({ visible: true }).click();
      await page.getByRole("link", { name: "Browse events" }).first().click();

      await expect(page).toHaveURL(/#g-conventions-heading$/);
      await expect(
        page.getByRole("heading", { name: "Enrollment and the programme in one place" }),
      ).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test("shows organizers' testimonials only in the organizer view", async ({ page }) => {
    await page.goto("/");

    const mamert = page.getByRole("figure", { name: "Mamert · Bachanalia Fantastyczne" });
    await expect(mamert).toContainText("Widzę jaki potencjał i pomoc jest w takiej aplikacji.");
    await expect(mamert.locator("img[src*='bachanalia-mark']")).toBeVisible();
    const avatar = mamert.locator("img[src*='mamert']");
    await expect(avatar).toBeVisible();
    await avatar.scrollIntoViewIfNeeded();
    await expect
      .poll(() => avatar.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);

    for (const name of ["Hory-portier", "Gosia", "Sowa"]) {
      const quote = page.getByRole("figure", { name: `${name} · Kapitularz` });
      await expect(quote).toBeVisible();
      await expect(quote.locator("img")).toHaveAttribute("src", /kapitularz-mark.*\.svg/);
    }
    await expect(page.getByRole("figure", { name: "Sowa · Kapitularz" })).toContainText(
      "ponad 900 godzin programu",
    );
    await expect(
      page.getByRole("heading", { name: "Four questions you probably have in mind" }),
    ).toHaveCSS("text-wrap", "balance");

    await page.getByText("For players", { exact: true }).filter({ visible: true }).click();
    await expect(mamert).toBeHidden();
  });

  for (const width of [375, 320]) {
    test(`fits every act of the six-acts stage on a ${width}px phone`, async ({
      page,
    }, testInfo) => {
      // NOTE: no CI browser has iOS 26.0's zoom-on-rem bug; this guards the
      // breakpoint layout's fit.
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");
      const grid = page.getByRole("group", { name: "The programme grid, scrollable sideways" });
      const stage = grid.locator(".stage");
      // elementFromPoint only sees what is in the viewport.
      await grid.scrollIntoViewIfNeeded();
      // The stage and its chips clip with overflow: hidden, so content that
      // does not fit is cut off rather than spilling: compare boxes instead.
      const overflowing = () =>
        stage.evaluate((stageEl) => {
          const inside = (inner: DOMRect, outer: DOMRect) =>
            inner.left >= outer.left - 1 &&
            inner.right <= outer.right + 1 &&
            inner.top >= outer.top - 1 &&
            inner.bottom <= outer.bottom + 1;
          const shown = (el: Element) => {
            const style = getComputedStyle(el);
            return (
              el.getClientRects().length > 0 &&
              style.visibility === "visible" &&
              style.opacity !== "0"
            );
          };
          const offenders: string[] = [];
          for (const box of stageEl.querySelectorAll(".ctx, .chip, .doorcard")) {
            if (!shown(box)) continue;
            const frame = box.getBoundingClientRect();
            if (!inside(frame, stageEl.getBoundingClientRect())) offenders.push(box.className);
            for (const child of box.children) {
              if (shown(child) && !inside(child.getBoundingClientRect(), frame)) {
                offenders.push(`${box.className} > ${child.textContent?.trim()}`);
              }
            }
            const title = box.querySelector(".ct");
            if (!title) continue;
            // A flex item never shrinks below its longest word, so a word wider
            // than the chip widens the title into the chip's padding. Offsets
            // ignore act 1's rotation.
            const chip = box as HTMLElement;
            const titleEl = title as HTMLElement;
            const contentRight = chip.clientWidth - parseFloat(getComputedStyle(chip).paddingRight);
            if (titleEl.offsetLeft + titleEl.offsetWidth > contentRight + 1) {
              offenders.push(`${box.className} > ${title.textContent?.trim()} into padding`);
            }
            // Badges and the warning dot keep 2px clear of the title's text.
            const range = document.createRange();
            range.selectNodeContents(title);
            const lines = [...range.getClientRects()];
            for (const child of box.children) {
              if (child === title || !shown(child)) continue;
              const r = child.getBoundingClientRect();
              const hit = lines.some(
                (line) =>
                  r.left < line.right + 2 &&
                  r.right > line.left - 2 &&
                  r.top < line.bottom + 2 &&
                  r.bottom > line.top - 2,
              );
              if (hit) offenders.push(`${box.className} > ${child.textContent?.trim()} on title`);
            }
            // Cards may overlap, as in act 1's pile, but never over a title.
            for (const line of lines) {
              for (const fraction of [0.02, 0.5, 0.98]) {
                const top = document.elementFromPoint(
                  line.left + line.width * fraction,
                  line.top + line.height / 2,
                );
                if (!box.contains(top)) {
                  offenders.push(`${box.className} > ${title.textContent?.trim()} under a card`);
                  break;
                }
              }
            }
          }
          // Room names and times sit in fixed-width columns.
          for (const label of stageEl.querySelectorAll(".rh, .tl")) {
            if (label.scrollWidth > label.clientWidth + 1) offenders.push(label.textContent ?? "");
          }
          // The context strip wraps on a phone; its rows must end above the grid.
          const strips = [...stageEl.querySelectorAll(".ctx")].filter(shown);
          if (strips.length !== 1) offenders.push(`${strips.length} strips shown`);
          const strip = strips[0];
          const stripBottom = strip?.getBoundingClientRect().bottom ?? 0;
          for (const below of stageEl.querySelectorAll(".rh, .chip")) {
            if (shown(below) && stripBottom > below.getBoundingClientRect().top + 1) {
              offenders.push(`${strip?.className} over ${below.className}`);
            }
          }
          return offenders;
        });

      for (const [index, act] of ["01", "02", "03", "04", "05", "06"].entries()) {
        await page.locator(`label[for="k${index + 1}"]`).click();
        await expect(page.getByRole("radio", { name: new RegExp(`^${act}\\b`) })).toBeChecked();
        await expect.poll(() => grid.evaluate((el) => el.scrollWidth - el.clientWidth)).toBe(0);
        // Chips glide into place; poll until the last one has landed.
        await expect.poll(overflowing).toEqual([]);
        const box = await stage.boundingBox();
        await attachArtifacts(testInfo, {
          name: `six-acts-${width}px-${act}`,
          region: grid,
          facts: { act, width, stage: box },
        });
      }
    });
  }

  for (const { width, fontSize } of [
    { width: 320, fontSize: 32 },
    { width: 375, fontSize: 16 },
    { width: 1920, fontSize: 24 },
  ]) {
    for (const language of ["en", "pl"]) {
      test(`keeps the enrollment animation and print layout stable at ${width}px in ${language}`, async ({
        page,
      }, testInfo) => {
        await page.setViewportSize({ width, height: 1080 });
        await page
          .context()
          .addCookies([
            { name: "django_language", value: language, url: testInfo.project.use.baseURL! },
          ]);
        await page.goto("/");
        await page.evaluate(async (fontSize) => {
          document.documentElement.style.fontSize = `${fontSize}px`;
          await document.fonts.ready;
        }, fontSize);

        const enrollment = page.getByRole("region", {
          name:
            language === "pl"
              ? "Grupa czeka razem i wchodzi razem"
              : "A group waits together and enters together",
        });
        await expect(enrollment).toBeVisible();
        const frames = await enrollment.evaluate(async (section) => {
          const animations = section.getAnimations({ subtree: true });
          for (const animation of animations) animation.pause();
          const frames: { height: number; nextTop: number; contentFits: boolean }[] = [];
          for (let time = 0; time <= 14000; time += 200) {
            for (const animation of animations) animation.currentTime = time;
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
            const box = section.getBoundingClientRect();
            const next = section.nextElementSibling!.getBoundingClientRect();
            const caption = section.querySelector(".p1-cap")!;
            const column = caption.parentElement!;
            frames.push({
              height: box.height,
              nextTop: next.top,
              contentFits:
                caption.getBoundingClientRect().bottom <= column.getBoundingClientRect().bottom + 1,
            });
          }
          return frames;
        });
        expect(
          Math.max(...frames.map((f) => f.height)) - Math.min(...frames.map((f) => f.height)),
        ).toBeLessThan(1);
        expect(
          Math.max(...frames.map((f) => f.nextTop)) - Math.min(...frames.map((f) => f.nextTop)),
        ).toBeLessThan(1);
        expect(frames.every((f) => f.contentFits)).toBe(true);
        for (const caption of await enrollment.locator(".p1-cap > p").all()) {
          await expect(caption).toHaveCSS("text-wrap-style", "pretty");
        }
        await enrollment.evaluate((section) => {
          for (const animation of section.getAnimations({ subtree: true }))
            animation.currentTime = 10000;
        });
        await attachArtifacts(testInfo, {
          name: `enrollment-${width}-${language}`,
          region: enrollment,
          facts: { width, fontSize, language, frames },
        });

        const print = page.getByRole("region", {
          name: language === "pl" ? "Ctrl+P i gotowe" : "Ctrl+P and done",
        });
        const papers = print.getByRole("img");
        const boxes = await papers.evaluate((cluster) =>
          [...cluster.children].map((paper) => {
            const { left, right, top, bottom } = paper.getBoundingClientRect();
            return { left, right, top, bottom };
          }),
        );
        expect(boxes[0].right).toBeGreaterThanOrEqual(boxes[1].left);
        expect(boxes[0].bottom).toBeGreaterThanOrEqual(boxes[1].top);
        await attachArtifacts(testInfo, {
          name: `print-${width}-${language}`,
          region: print,
          facts: { width, language, boxes },
        });
      });
    }
  }

  for (const width of [375, 1440]) {
    test(`shows the whole wide convention cover at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.route("**/placeholder-images/03.webp", (route) =>
        route.fulfill({
          contentType: "image/svg+xml",
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="1268" height="468" viewBox="0 0 1268 468"><rect width="1268" height="468" fill="#245575"/><rect x="10" y="10" width="1248" height="448" fill="none" stroke="#f7d774" stroke-width="20"/><text x="634" y="220" fill="white" font-size="54" text-anchor="middle">Full cover, including both edges</text></svg>',
        }),
      );
      await page.goto("/");
      const proof = page.getByRole("region", { name: /^events$/i });
      const covers = proof.locator("img");
      await expect(covers).toHaveCount(3);
      for (const cover of await covers.all()) {
        await cover.scrollIntoViewIfNeeded();
        await expect
          .poll(() => cover.evaluate((image: HTMLImageElement) => image.naturalWidth))
          .toBe(1268);
        await expect(cover).toHaveCSS("object-fit", "cover");
        const visibleFraction = await cover.evaluate((image: HTMLImageElement) => {
          const { width, height } = image.getBoundingClientRect();
          const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
          return Math.min(
            width / (scale * image.naturalWidth),
            height / (scale * image.naturalHeight),
          );
        });
        expect(visibleFraction).toBeGreaterThan(0.99);
        await cover.hover();
        await expect(cover).toHaveCSS("transform", "none");
      }
      await attachArtifacts(testInfo, {
        name: `landing-covers-${width}`,
        region: proof,
        facts: { width, sourceWidth: 1268, sourceHeight: 468 },
      });
    });
  }

  test("prints the final act without white schedule cards in dark mode", async ({
    page,
  }, testInfo) => {
    await page.goto("/");
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    const grid = page.getByRole("group", { name: "The programme grid, scrollable sideways" });
    await page.locator('label[for="k6"]').click();
    const schedule = grid.getByText("Opening talk", { exact: true });
    await expect(schedule).toBeVisible();
    for (const card of await grid.locator(".chip").all()) {
      await expect(card).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    }
    await grid.evaluate((el) =>
      Promise.all(el.getAnimations({ subtree: true }).map((animation) => animation.finished)),
    );
    await expect(schedule).toHaveCSS(
      "color",
      await grid.evaluate((el) => getComputedStyle(el).color),
    );
    await attachArtifacts(testInfo, {
      name: "print-act-dark",
      region: grid,
      facts: { theme: "dark", act: 6 },
    });
  });

  test("#gracze deep link opens the player view directly", async ({ page }) => {
    await page.goto("/#gracze");

    await expect(page.getByRole("heading", { name: /Your table, your game/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();
  });

  test("keeps the plain feed on a sphere domain, announcements first", async ({ page }) => {
    await page.goto("http://foreign.localhost:8000/");

    await expect(page.getByRole("heading", { name: "Upcoming" })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Event organization/ })).toBeHidden();

    // A sphere's announcements sit above its programme. The root sphere runs
    // no programme and shows none.
    await expect(page.getByRole("heading", { name: "Organization announcements" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Doors open at 9:00" })).toBeVisible();

    // The feed's cards reach their event — coverage that lived in
    // index.spec.ts, against the root domain, which is the pitch now. Located
    // by href: the sphere and its event share a name, so the navbar's brand
    // link answers to the same accessible name.
    await page.locator('#events a[href="/event/foreign-programme/"]').first().click();
    await expect(page).toHaveURL(/\/event\/foreign-programme\//);
  });
});
