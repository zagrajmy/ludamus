import { expect, test } from "./helpers/fixtures";

// accept-lab is seeded with one bookable room and one time slot, so the
// scheduling form has nothing to ask. The organizer still has to be told
// where and when they are about to put the session. Accepting consumes a
// pending proposal, so the two scenarios run serially against one each.
test.describe.configure({ mode: "serial" });

const EVENT = "accept-lab";
const ROOM = "The Only Room";

async function reviewProposal(page: import("@playwright/test").Page, title: string) {
  await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Username:").fill("e2e-manager");
  await page.getByLabel("Password:").fill("e2e-manager-123");
  await page.getByRole("button", { name: /Log in/i }).click();
  await page.goto(`/event/${EVENT}/`);
  await page.getByRole("link", { name: `Review proposal ${title}` }).click();
  return page.getByRole("heading", { name: "Schedule it" }).locator("..");
}

test.describe("Accepting a proposal", () => {
  test("a foregone space and time are named, not asked for", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Showcase");

    // Nothing to choose, so the decision card asks nothing.
    await expect(decision.getByRole("combobox")).toHaveCount(0);

    // It names what the button is about to commit to instead.
    await expect(decision.getByText("Space", { exact: true })).toBeVisible();
    await expect(decision.getByText(ROOM)).toBeVisible();
    await expect(decision.getByText("Time slot", { exact: true })).toBeVisible();
    await expect(decision.getByRole("button", { name: "Accept and add to agenda" })).toBeVisible();
  });

  test("the decision card stays clear of the sticky navbar", async ({ page }) => {
    // Short enough that the proposal column scrolls past the card, which then
    // pins itself under the navbar instead of sliding beneath it.
    await page.setViewportSize({ width: 1280, height: 480 });
    const card = (await reviewProposal(page, "Solo Showcase")).locator("..");

    // The document never scrolls; #app-scroll owns the scroll (see base.html).
    const scroller = page.locator("#app-scroll");
    // Far enough for the card to pin, short of the grid's end pushing it back up.
    await scroller.evaluate((el) => el.scrollTo(0, 150));
    await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBe(150);

    const navBox = await page.locator("nav").first().boundingBox();
    const cardBox = await card.boundingBox();
    expect(cardBox!.y).toBeGreaterThanOrEqual(navBox!.y + navBox!.height);
  });

  test("the room and time it names are the ones it submits", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Encore");
    const [namedRoom, namedSlot] = await decision.locator("dd").allInnerTexts();

    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));

    // A hidden value nobody saw could schedule somewhere else, so the booking
    // has to read back as the room and the hours the card named.
    await page.getByRole("link", { name: "Open details for Solo Encore" }).click();
    const details = page.getByRole("dialog");
    await expect(details).toContainText(namedRoom.trim());
    const [start, end] = namedSlot.trim().split("–");
    await expect(details).toContainText(`${start.slice(-5)} - ${end}`);
  });
});
