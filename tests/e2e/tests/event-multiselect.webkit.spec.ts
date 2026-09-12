import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });

test("keeps multiple picks when the touch keyboard releases focus", async ({ page }) => {
  await page.goto(DENSE_EVENT_URL);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const track = page.getByRole("combobox", { name: "Track", exact: true });
  for (const name of ["RPG", "Cosplay"]) {
    await track.fill(name);
    await track.press("Enter");
    await expect(track).not.toBeFocused();
    await expect(track).toHaveAttribute("aria-expanded", "false");
  }
  await expect(track).toHaveValue("RPG, Cosplay");
  await page.getByRole("button", { name: "Apply filters", exact: true }).click();
  await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(2);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("track"))
    .toBe(JSON.stringify(["RPG", "Cosplay"]));
  await page.reload();
  await page.getByRole("button", { name: "Remove filter: RPG", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Remove filter: Cosplay", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /^Remove filter:/ })).toHaveCount(1);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(track).toHaveValue("Cosplay");
});
