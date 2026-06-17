import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

/**
 * Assert the page has no critical or serious WCAG 2.1 AA accessibility
 * violations. Gates the two most severe impact levels from day one.
 */
export const analyzePageAccessibility = async (
  page: Page,
  options: { include?: string } = {},
): Promise<void> => {
  let builder = new AxeBuilder({ page }).withTags([
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
  ]);
  if (options.include) builder = builder.include(options.include);

  const results = await builder.analyze();
  const blocking = results.violations.filter(
    (violation) =>
      violation.impact === "critical" || violation.impact === "serious",
  );

  expect(
    blocking,
    `Accessibility violations:\n${blocking
      .map(
        (v) => `- [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s))`,
      )
      .join("\n")}`,
  ).toEqual([]);
};
