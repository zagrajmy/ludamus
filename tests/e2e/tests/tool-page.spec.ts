import { assertNoCspViolations, installCspViolationCollector } from "./helpers/csp";
import { expect, test } from "./helpers/fixtures";
import { CREW_SPHERE } from "./helpers/urls";

// bootstrap_data.py seeds this tool. The spec answers for its address, so the
// frame loads a real https document without a request leaving the machine.
const TOOL_ADDRESS = "https://tables.example.test/";

test.describe("Catalogue tool on a sphere page", () => {
  test("the tool runs in a frame between the site header and footer", async ({ page }) => {
    await page.route(`${TOOL_ADDRESS}**`, (route) =>
      route.fulfill({ contentType: "text/html", body: "<h1>Pick a table</h1>" }),
    );
    await installCspViolationCollector(page);

    await page.goto(`${CREW_SPHERE}/tools/table-manager/`);

    await expect(
      page.getByRole("navigation").getByRole("link", { name: "Crew Sphere" }),
    ).toBeVisible();
    await expect(page.getByRole("contentinfo")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Table Manager", level: 1 })).toBeVisible();
    // SAFETY: with default-src 'none' the frame loads only when the page's
    // policy names the tool's domain, so this heading proves the override.
    await expect(
      page
        .getByTitle("Table Manager")
        .contentFrame()
        .getByRole("heading", { name: "Pick a table" }),
    ).toBeVisible();
    await assertNoCspViolations(page);
  });

  test("a link opens the tool in a new tab", async ({ page }) => {
    await page.route(`${TOOL_ADDRESS}**`, (route) => route.abort());

    await page.goto(`${CREW_SPHERE}/tools/table-manager/`);

    const link = page.getByRole("link", { name: "Open in a new tab" });
    await expect(link).toHaveAttribute("href", TOOL_ADDRESS);
    await expect(link).toHaveAttribute("target", "_blank");
  });
});
