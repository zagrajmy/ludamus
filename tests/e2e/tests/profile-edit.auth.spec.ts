import path from "node:path";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-profile.json") });

const PROFILE_URL = "/crowd/profile/";
const TAKEN_EMAIL = "e2e@test.local";
const OWN_EMAIL = "e2e-profile@test.local";
const NEW_NAME = "Wren Hollis-Tide";

test.describe("Editing your own profile", () => {
  test("a taken email is refused, a rename persists, and the signup belongs on the dashboard", async ({
    page,
  }, testInfo) => {
    await page.goto(PROFILE_URL);
    const name = page.getByLabel("Display name");
    const email = page.getByLabel("email address", { exact: true });

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
    await expect(page.getByText(/confirmed session participation/)).toHaveCount(0);
    await expect(page.getByText("Your email address is verified.")).toHaveCount(0);

    const facts = {
      displayName: await name.inputValue(),
      email: await email.inputValue(),
    };
    expect(facts).toEqual({ displayName: NEW_NAME, email: OWN_EMAIL });
    await attachArtifacts(testInfo, {
      name: "profile-edit",
      region: page.getByRole("main"),
      facts,
    });

    await page.goto("/dashboard/");
    const comingUp = page.getByRole("region", { name: "Coming up" });
    const signup = comingUp.getByRole("link", { name: /Lighthouse Mysteries/ });
    await expect(signup).toContainText("Tidewater Games Night");
    await expect(signup).toContainText("You're signed up");
    await expect(signup).toContainText("Chart Room");
    await expect(signup).toContainText(/\d{1,2} \w+, \d{2}:\d{2}/);
    await expect(signup).toHaveAttribute(
      "href",
      /\/event\/tidewater-night\/session\/\d+\/enrollment\/$/,
    );
    await attachArtifacts(testInfo, {
      name: "profile-dashboard-signup",
      region: comingUp,
      facts: { signup: await signup.innerText(), url: await signup.getAttribute("href") },
    });
    await signup.click();
    await expect(
      page.getByRole("heading", { name: "Lighthouse Mysteries", exact: true }),
    ).toBeVisible();
  });

  test("profile and dashboard remain readable on a narrow viewport", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(PROFILE_URL);
    await expect(page.getByLabel("Display name")).toBeVisible();
    await expect(page.getByText(/confirmed session participation/)).toHaveCount(0);
    await attachArtifacts(testInfo, {
      name: "profile-mobile",
      region: page.getByRole("main"),
      facts: { viewport: page.viewportSize() },
    });
    await page.goto("/dashboard/");
    const comingUp = page.getByRole("region", { name: "Coming up" });
    await expect(comingUp.getByRole("link", { name: /Lighthouse Mysteries/ })).toBeVisible();
    await attachArtifacts(testInfo, {
      name: "dashboard-mobile",
      region: page.getByRole("main"),
      facts: { viewport: page.viewportSize() },
    });
  });
});
