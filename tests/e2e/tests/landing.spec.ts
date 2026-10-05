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
