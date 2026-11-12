import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

for (const width of [375, 1280]) {
  for (const theme of ["light", "dark"]) {
    for (const reducedMotion of ["no-preference", "reduce"] as const) {
      test(`flattens print cards together at ${width}px in ${theme} with ${reducedMotion} motion`, async ({
        page,
      }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        await page.emulateMedia({
          colorScheme: theme === "dark" ? "dark" : "light",
          reducedMotion,
        });
        await page.goto("/");
        await page.evaluate(async (theme) => {
          document.documentElement.classList.toggle("dark", theme === "dark");
          await document.fonts.ready;
        }, theme);
        const grid = page.getByRole("group", { name: "The programme grid, scrollable sideways" });
        await grid.scrollIntoViewIfNeeded();
        const enrollment = page.getByRole("radio", { name: /^05\b/ });
        const print = page.getByRole("radio", { name: /^06\b/ });
        await enrollment.focus();
        await enrollment.press("Space");
        await expect(enrollment).toBeChecked();
        await grid.evaluate((el) =>
          Promise.all(el.getAnimations({ subtree: true }).map((animation) => animation.finished)),
        );

        const sample = async (targetId: string) =>
          grid.evaluate(async (el, targetId) => {
            const cards = [...el.querySelectorAll<HTMLElement>(".chip")];
            document.getElementById(targetId)!.click();
            cards[0].getBoundingClientRect();
            const animations = el.getAnimations({ subtree: true });
            for (const animation of animations) animation.pause();
            const frames = [];
            for (let frame = 0; frame <= 36; frame++) {
              const time = (frame * 1000) / 60;
              for (const animation of animations) animation.currentTime = time;
              await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
              frames.push({
                time,
                cards: cards.map((card) => {
                  const style = getComputedStyle(card);
                  const title = card.querySelector<HTMLElement>(".ct")!;
                  return {
                    borders: ["Top", "Right", "Bottom", "Left"].map((side) =>
                      style.getPropertyValue(`border-${side.toLowerCase()}-width`),
                    ),
                    inset: title.getBoundingClientRect().left - card.getBoundingClientRect().left,
                    borderColor: style.borderTopColor,
                    filter: style.filter,
                  };
                }),
              });
            }
            return frames;
          }, targetId);

        const entering = await sample((await print.getAttribute("id"))!);
        await expect(print).toBeChecked();
        expect(entering).toHaveLength(37);
        for (const frame of entering) {
          for (const card of frame.cards) {
            expect(card.borders, `border at ${frame.time}ms`).toEqual(["0px", "0px", "0px", "0px"]);
            expect(card.inset, `title inset at ${frame.time}ms`).toBeCloseTo(1, 1);
          }
        }
        expect(entering.at(-1)!.cards.every((card) => card.filter === "grayscale(1)")).toBe(true);
        if (reducedMotion === "no-preference") {
          const early = entering[6].cards;
          expect(early[0].filter).toMatch(/^grayscale\(0\.\d+\)$/);
          expect(early[6].filter).toMatch(/^(none|grayscale\(0\))$/);
        }
        await attachArtifacts(testInfo, {
          name: `print-enter-${width}-${theme}-${reducedMotion}`,
          region: grid,
          facts: { width, theme, reducedMotion, frames: entering },
        });

        const leaving = await sample((await enrollment.getAttribute("id"))!);
        await expect(enrollment).toBeChecked();
        for (const frame of leaving) {
          for (const card of frame.cards) {
            expect(card.borders, `restored border at ${frame.time}ms`).toEqual([
              "1px",
              "1px",
              "1px",
              "1px",
            ]);
          }
        }
        if (reducedMotion === "no-preference") {
          expect(leaving[0].cards.every((card) => card.borderColor === "rgba(0, 0, 0, 0)")).toBe(
            true,
          );
          expect(leaving[6].cards[6].borderColor).toBe("rgba(0, 0, 0, 0)");
        }
        expect(leaving.at(-1)!.cards.every((card) => card.borderColor !== "rgba(0, 0, 0, 0)")).toBe(
          true,
        );
        await attachArtifacts(testInfo, {
          name: `print-leave-${width}-${theme}-${reducedMotion}`,
          region: grid,
          facts: { width, theme, reducedMotion, frames: leaving },
        });
      });
    }
  }
}
