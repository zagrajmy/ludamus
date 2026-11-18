import { attachArtifacts } from "./helpers/artifacts";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

// NOTE: runs add events nobody can delete; a 2001 start keeps /panel/ redirects as is.
const START = "2001-06-01T10:00";
const END = "2001-06-01T18:00";

test.describe("Event visibility", () => {
  test.use({ storageState: managerState });

  test("a new event waits for a publication time until it is made public", async ({
    page,
  }, testInfo) => {
    const slug = `visibility-${Date.now()}`;
    await page.goto("/panel/events/new/");
    await page.getByLabel("Name").fill("Visibility check");
    await page.getByLabel("Slug").fill(slug);
    await page.getByLabel("Start time").fill(START);
    await page.getByLabel("End time").fill(END);
    await page.getByLabel("Based on").selectOption({ label: "No event, start empty" });
    await page.getByRole("button", { name: "Create event" }).click();
    await page.waitForURL(`**/panel/event/${slug}/`);

    await page.goto(`/panel/event/${slug}/settings/`);
    const scheduled = page.getByRole("radio", { name: /^Publish at a set time/ });
    const publishAt = page.getByLabel("Publish at", { exact: true });
    await expect(scheduled).toBeChecked();
    await expect(publishAt).toBeVisible();
    await expect(publishAt).toHaveValue("");

    const publicNow = page.getByRole("radio", { name: /^Public now/ });
    await publicNow.check();
    await expect(publishAt).toBeHidden();
    await page.getByRole("radio", { name: /^Link only/ }).check();
    await expect(publishAt).toBeHidden();
    await publicNow.check();
    await page.getByRole("button", { name: "Save Settings" }).click();

    await expect(page.getByText("Event settings saved successfully.")).toBeVisible();
    await expect(publicNow).toBeChecked();
    await expect(publishAt).toBeHidden();
    await page.getByRole("heading", { name: "Visibility" }).scrollIntoViewIfNeeded();
    await attachArtifacts(testInfo, {
      name: "event-visibility",
      region: page.locator("body"),
      facts: { slug },
    });
  });
});
