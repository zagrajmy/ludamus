import path from "node:path";

import { expect, test } from "./helpers/fixtures";

const proposeUrl = "/event/mothership-nights-2/session/propose/";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-reuser.json") });

test.describe("Cover designer on the session proposal", () => {
  test("is offered beside the cover, and its text starts empty, not as the title", async ({
    page,
  }) => {
    await page.goto(proposeUrl);
    const form = page.locator("#propose-details-form");
    await form.getByRole("textbox", { name: "Title" }).fill("Mothership for first-timers");

    await page.getByRole("button", { name: "Design a cover" }).click();
    const dialog = page.getByRole("dialog", { name: "Design a cover" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("radio", { name: "Add text" }).check();
    await expect(dialog.getByRole("textbox", { name: "Text", exact: true })).toHaveValue("");

    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
    await expect(form.getByRole("textbox", { name: "Title" })).toHaveValue(
      "Mothership for first-timers",
    );
  });
});
