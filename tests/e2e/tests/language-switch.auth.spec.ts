import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// NOTE: the profile account, not the shared tester: a signed-in switch is
// also recorded on the user row, as the language we write to them in.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-profile.json") });

// The suite's browsers ask for English; the site's own default is Polish.
// A choice made here has to beat both, and outlive the page it was made on.
test.describe("Language switch on the profile", () => {
  test("switches the site and the choice sticks", async ({ page }) => {
    await page.goto("/crowd/profile/");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    const languages = page.getByRole("group", { name: "Language" });
    await expect(languages.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await languages.getByRole("button", { name: "Polski" }).click();

    await expect(page).toHaveURL(/\/crowd\/profile\/$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "pl");
    const jezyk = page.getByRole("group", { name: "Język" });
    await expect(jezyk.getByRole("button", { name: "Polski" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await page.goto("/about/");
    await expect(page.getByRole("heading", { level: 1, name: "O Zagrajmy" })).toBeVisible();

    await page.goto("/crowd/profile/");
    await page
      .getByRole("group", { name: "Język" })
      .getByRole("button", { name: "English" })
      .click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });
});
