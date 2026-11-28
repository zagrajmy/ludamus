import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

test.describe("Public host name never shows an email", () => {
  test("session card and modal show the local-part, not the address", async ({
    page,
  }, testInfo) => {
    await page.goto("/event/privacy-host/");
    const card = page.getByRole("article").filter({ hasText: "Berdysz k10" });
    await expect(card).toBeVisible();
    await expect(card.getByText("redziniak.w", { exact: true })).toBeVisible();
    await expect(card.getByText("@gmail.com")).toHaveCount(0);
    await expect(card.getByText("redziniak.w@gmail.com")).toHaveCount(0);

    await card.getByRole("link", { name: "Open details for Berdysz k10" }).press("Enter");
    const dialog = page.getByRole("dialog", { name: "Berdysz k10" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("redziniak.w", { exact: true })).toBeVisible();
    await expect(dialog.getByText("redziniak.w@gmail.com")).toHaveCount(0);
    await attachArtifacts(testInfo, {
      name: "public-host-local-part",
      region: dialog,
      facts: { host: "redziniak.w", emailHidden: true },
    });
  });
});
