import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

// NOTE: Wren Hollis (bootstrap_data.py) is this spec's own participant, with
// one confirmed seat on Tidewater Games Night. The walkthrough renames her to
// the same name every run, so it never depends on where the last run left her.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-profile.json") });

const PROFILE_URL = "/crowd/profile/";
const TAKEN_EMAIL = "e2e@test.local";
const OWN_EMAIL = "e2e-profile@test.local";
const NEW_NAME = "Wren Hollis-Tide";

test.describe("Editing your own profile", () => {
  test("a taken email is refused with the form kept, then a rename saves and survives a reload next to her confirmed-seats count", async ({
    page,
  }, testInfo) => {
    await page.goto(PROFILE_URL);
    const name = page.getByLabel("Display name");
    const email = page.getByLabel("email address");

    await name.fill(NEW_NAME);
    await email.fill(TAKEN_EMAIL);
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("Please correct the errors below.")).toBeVisible();
    await expect(
      page.getByText("This email address is already in use. Please use a different email address."),
    ).toBeVisible();
    await expect(name).toHaveValue(NEW_NAME);
    await expect(email).toHaveValue(TAKEN_EMAIL);

    await email.fill(OWN_EMAIL);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Profile updated successfully!")).toBeVisible();

    await page.reload();
    await expect(name).toHaveValue(NEW_NAME);
    await expect(email).toHaveValue(OWN_EMAIL);
    const banner = page.getByText(/You have \d+ confirmed session participation/);
    await expect(banner).toHaveText("You have 1 confirmed session participation.");

    const facts = {
      displayName: await name.inputValue(),
      email: await email.inputValue(),
      confirmedBanner: (await banner.innerText()).trim(),
    };
    expect(facts).toEqual({
      displayName: NEW_NAME,
      email: OWN_EMAIL,
      confirmedBanner: "You have 1 confirmed session participation.",
    });
    await attachArtifacts(testInfo, {
      name: "profile-edit",
      region: page.getByRole("main"),
      facts,
    });
  });
});
