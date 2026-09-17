import { expect, test } from "./helpers/fixtures";

// accept-lab is seeded with one bookable room, so the space is foregone and the
// card names it rather than asking. The time is a real field now: the organizer
// picks when the session runs. Accepting consumes a pending proposal, so the
// two scenarios run serially against one each.
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
  test("a foregone space is named, and the time is asked for", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Showcase");

    // One room means no picker; the card names what it will commit to.
    await expect(decision.getByRole("combobox")).toHaveCount(0);
    await expect(decision.getByText("Space", { exact: true })).toBeVisible();
    await expect(decision.getByText(ROOM)).toBeVisible();

    // The time is a genuine choice, so it is a field, pre-filled with the
    // event's opening hour rather than left blank.
    const startsAt = decision.getByLabel("Starts at");
    await expect(startsAt).toBeVisible();
    await expect(startsAt).not.toHaveValue("");
    await expect(decision.getByRole("button", { name: "Accept and add to agenda" })).toBeVisible();
  });

  test("the time it is given is the time it books", async ({ page }) => {
    const decision = await reviewProposal(page, "Solo Encore");
    const startsAt = decision.getByLabel("Starts at");
    const chosen = (await startsAt.inputValue()).slice(0, 16);

    await decision.getByRole("button", { name: "Accept and add to agenda" }).click();
    await expect(page).toHaveURL(new RegExp(`/event/${EVENT}/$`));

    // A hidden value nobody saw could schedule somewhere else, so the booking
    // has to read back as the room and the hour the form carried.
    await page.getByRole("link", { name: "Open details for Solo Encore" }).click();
    const details = page.getByRole("dialog");
    await expect(details).toContainText(ROOM);
    await expect(details).toContainText(chosen.slice(-5));
  });
});
