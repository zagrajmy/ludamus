import { expect, test } from "@playwright/test";

const densePrintUrl = "/event/kapitularz-2025-anonymized/print/";

const countPdfPages = (pdf: Buffer) => {
  const text = pdf.toString("latin1");
  return [...text.matchAll(/\/Type\s*\/Page\b/g)].length;
};

test.describe("Public print page", () => {
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
      ["timetable", "Timetable"],
      ["timetable-descriptions", "Timetable with descriptions"],
      ["track-timetable", "Track timetable"],
    ] as const;

    await page.goto(densePrintUrl);
    const select = page.getByLabel("Printable");

    for (const [, label] of materials) {
      await expect(select.getByRole("option", { name: label, exact: true })).toHaveCount(1);
    }
    await expect(select.getByRole("option", { name: "Session list" })).toHaveCount(0);
  });
});
