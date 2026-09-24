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

test("a swipe that starts on an option picks nothing, and a tap still does", async ({ page }) => {
  await page.goto(DENSE_EVENT_URL);
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  const host = page.getByRole("combobox", { name: "Host", exact: true });
  await host.click();
  const options = page.getByRole("listbox", { name: "Host", exact: true }).getByRole("option");
  const first = options.first();
  await expect(first).toHaveAttribute("aria-selected", "false");
  const box = await first.boundingBox();
  if (!box) throw new Error("option is not laid out");
  const finger = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
  const touch = { pointerType: "touch", isPrimary: true };
  // A finger landing on the row and leaving for a scroll: the browser takes
  // the gesture and cancels the pointer, so no click ever arrives.
  await first.dispatchEvent("pointerdown", { ...touch, ...finger });
  await first.dispatchEvent("pointercancel", touch);
  await expect(first).toHaveAttribute("aria-selected", "false");
  await expect(host).toHaveValue("");
  // The same swipe with nothing left to scroll still lifts the finger from
  // the row it landed on (a touch pointer is captured by it), 60px away.
  await first.dispatchEvent("pointerdown", { ...touch, ...finger });
  await first.dispatchEvent("pointermove", { ...touch, ...finger, clientY: finger.clientY - 60 });
  await first.dispatchEvent("pointerup", { ...touch, ...finger, clientY: finger.clientY - 60 });
  await expect(first).toHaveAttribute("aria-selected", "false");
  await expect(host).toHaveValue("");
  await expect(host).toHaveAttribute("aria-expanded", "true");
  // A tap still picks, and lets go of the input as every touch pick does.
  const firstName = (await first.textContent())?.trim() ?? "";
  expect(firstName).not.toBe("");
  await first.tap();
  await expect(host).toHaveValue(firstName);
  await expect(host).not.toBeFocused();
});
