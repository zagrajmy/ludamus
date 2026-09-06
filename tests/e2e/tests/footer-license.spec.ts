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

  // The stacked footer used to align its children to the start of a flex
  // column, which sizes them shrink-to-fit. The notice then rendered in a box
  // as wide as its longest line with a third of the row left empty, and
  // WebKit wrapped "AGPL-3.0." onto a line of its own inside it.
  test("gives the notice the full width once the footer stacks", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto("/");

    const notice = page.locator("footer p").filter({ hasText: "Source code" });
    const noticeBox = (await notice.boundingBox())!;
    const rowBox = (await notice.locator("xpath=..").boundingBox())!;

    expect(noticeBox.width).toBe(rowBox.width);
  });
});
