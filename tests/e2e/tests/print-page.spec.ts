import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";

const densePrintUrl = "/event/kapitularz-2025-anonymized/print/";

const countPdfPages = (pdf: Buffer) => {
  const text = pdf.toString("latin1");
  return [...text.matchAll(/\/Type\s*\/Page\b/g)].length;
};

test.describe("Public print page", () => {
  test("defaults to the participant program, one sheet per day", async ({ page }) => {
    await page.goto(densePrintUrl);

    await expect(page.getByLabel("Printable")).toHaveValue("session-list");
    // No scope, track, or time-window controls: a participant prints it all.
    await expect(page.getByLabel("Scope")).toHaveCount(0);
    await expect(page.getByLabel("Start")).toHaveCount(0);

    const preview = page.getByRole("region", { name: "Print preview" });
    const sheets = preview.getByRole("group");
    await expect(sheets).toHaveCount(3);
    const rows = sheets.nth(0).getByRole("row");
    await expect(rows.nth(1)).toContainText(/\d{2}:\d{2}–\d{2}:\d{2}/);
    await expect(sheets.nth(0)).toContainText("Open Play B");

    // Descriptions fold into the rows rather than swapping the document: the
    // same sheet, the same first session, more text under it.
    const bare = await sheets.nth(0).getByRole("row").nth(1).innerText();
    await page.getByLabel("With descriptions").check();
    await expect(page).toHaveURL(/descriptions=1/);
    await expect(page.getByLabel("Printable")).toHaveValue("session-list");
    const described = preview.getByRole("group").nth(0).getByRole("row").nth(1);
    await expect(described).toContainText(bare.split("\n")[0]);
    expect((await described.innerText()).length).toBeGreaterThan(bare.length);
  });

  test("renders dense event timetable as chunked sideways preview pages", async ({
    browserName,
    page,
  }) => {
    await page.goto(`${densePrintUrl}?material=timetable`);

    await expect(page.getByRole("heading", { name: "Timetable" }).first()).toBeVisible();
    await expect(page.getByText("Kapitularz 2025 Anonymized").first()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Table of contents" })).toBeVisible();

    const preview = page.getByRole("region", { name: "Print preview" });
    const previewPages = preview.getByRole("group");
    await expect(previewPages).toHaveCount(21);
    await expect(previewPages.nth(0)).toContainText("Workshop Studio - RPG Table 2");
    await expect(previewPages.nth(6)).toContainText("Open Play B");

    // The rooms grid: a tile sits in its room's column on the row it starts
    // and spans the rows it covers, placed by the nonced stylesheet rather
    // than auto-flowed.
    const placements = await previewPages
      .nth(0)
      .getByRole("article")
      .evaluateAll((elements) =>
        elements.map((element) => {
          const style = getComputedStyle(element);
          return {
            col: Number(element.dataset.col) + 1,
            row: Number(element.dataset.row) + 1,
            span: Number(element.dataset.span),
            gridColumnStart: style.gridColumnStart,
            gridRowStart: style.gridRowStart,
            gridRowEnd: style.gridRowEnd,
          };
        }),
      );
    expect(placements.length).toBeGreaterThan(0);
    for (const placement of placements) {
      expect(placement.gridColumnStart).toBe(String(placement.col));
      expect(placement.gridRowStart).toBe(String(placement.row));
      expect(placement.gridRowEnd).toBe(`span ${placement.span}`);
    }
    expect(placements.some((placement) => placement.span > 1)).toBe(true);
    await analyzePageAccessibility(page, { include: '[role="region"]' });

    const scrollMetrics = await preview.evaluate((preview) => ({
      clientWidth: preview.clientWidth,
      scrollWidth: preview.scrollWidth,
    }));
    expect(scrollMetrics.scrollWidth).toBeGreaterThan(scrollMetrics.clientWidth);

    await page.emulateMedia({ media: "print" });
    await expect(page.getByRole("navigation", { name: "Table of contents" })).toBeHidden();

    if (browserName === "chromium") {
      const pdf = await page.pdf({
        printBackground: true,
        preferCSSPageSize: true,
      });
      expect(pdf.subarray(0, 4).toString()).toBe("%PDF");
      expect(countPdfPages(pdf)).toBe(await previewPages.count());
    }
  });

  test("offers dense-fixture printable materials", async ({ page }) => {
    const materials = [
      ["session-list", "Program for participants"],
      ["timetable", "Timetable"],
      ["track-timetable", "Track timetable"],
      ["door-cards", "Door cards"],
    ] as const;

    await page.goto(densePrintUrl);
    const select = page.getByLabel("Printable");

    for (const [, label] of materials) {
      await expect(select.getByRole("option", { name: label, exact: true })).toHaveCount(1);
    }
    await expect(page.getByLabel("With descriptions")).not.toBeChecked();
  });

  test("descriptions checkbox swaps the grid for a per-space list", async ({ page }) => {
    await page.goto(`${densePrintUrl}?material=timetable`);

    await page.getByLabel("With descriptions").check();

    await expect(page).toHaveURL(/descriptions=1/);
    await expect(page.getByRole("heading", { name: "Program details" }).first()).toBeVisible();
    await expect(page.getByLabel("With descriptions")).toBeChecked();
  });
});
