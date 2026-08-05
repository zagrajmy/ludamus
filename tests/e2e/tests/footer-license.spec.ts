import { expect, test } from "./helpers/fixtures";

// The license notice is one blocktranslate unit with the anchors inside the
// msgid, so the failure mode isn't wrong wording — it's the markup arriving
// escaped and the sentence rendering as literal `<a href=...>` text. Assert the
// links resolve, not just that the words are present.
test.describe("Footer license notice", () => {
  test("offers the source under AGPL-3.0 with working links", async ({ page }) => {
    await page.goto("/");

    const notice = page.locator("footer p").filter({ hasText: "Source code" });
    await expect(notice).toContainText("available under");

    await expect(notice.getByRole("link", { name: "Source code" })).toHaveAttribute(
      "href",
      "https://github.com/zagrajmy/ludamus",
    );
    await expect(notice.getByRole("link", { name: "AGPL-3.0" })).toHaveAttribute(
      "href",
      "https://github.com/zagrajmy/ludamus/blob/main/LICENSE",
    );
  });
});
