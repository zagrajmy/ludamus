import { expect, test } from "./helpers/fixtures";

// The documents are Polish whatever the interface language is, so these
// assertions read the document's own headings rather than translated chrome.
test.describe("Legal documents", () => {
  test("privacy policy renders from the markdown file", async ({ page }) => {
    await page.goto("/privacy-policy/");

    await expect(page.getByRole("heading", { name: "POLITYKA PRYWATNOŚCI" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "1. ADMINISTRATOR DANYCH" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Back to Home/ })).toBeVisible();
  });

  test("terms of service renders from the markdown file", async ({ page }) => {
    await page.goto("/terms-of-service/");

    await expect(page.getByRole("heading", { name: "REGULAMIN SERWISU" })).toBeVisible();
    await expect(page.getByRole("listitem").first()).toBeVisible();
  });

  test("the old flatpage URL still lands on the policy", async ({ page }) => {
    await page.goto("/page//privacy-policy/");

    await expect(page).toHaveURL(/\/privacy-policy\/$/);
    await expect(page.getByRole("heading", { name: "POLITYKA PRYWATNOŚCI" })).toBeVisible();
  });

  test("the footer links to both documents", async ({ page }) => {
    await page.goto("/");

    const footer = page.locator("footer");
    await expect(footer.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
      "href",
      "/privacy-policy/",
    );
    await expect(footer.getByRole("link", { name: "Terms of Service" })).toHaveAttribute(
      "href",
      "/terms-of-service/",
    );
  });
});
